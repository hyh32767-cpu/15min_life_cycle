# -*- coding: utf-8 -*-
"""QPS 限流器、单飞请求合并、过期缓存兜底与快速预估先行 -> 后台全量升级单元测试。"""
from __future__ import annotations

import sqlite3
import threading
import time
import pytest
from pathlib import Path
from typing import Any, Dict, List

from core.isochrone import compute_l2_isochrone, infer_detour_factor
from core.ratelimit import AdaptiveRateLimiter, Singleflight, TokenBucket
from api.app.config import Settings
from api.app.models.common import Coord
from api.app.services.baidu_service import BaiduService
from api.app.services.errors import ServiceError
from api.app.services.isochrone_service import IsochroneService
from api.app.storage.api_cache import ApiCache
from api.app.storage.derived_cache import DerivedCache
from api.app.storage.ledger import ProductLedger


class _RawResult:
    def __init__(self, status: int, data: Dict[str, Any], message: str = "ok", attempts: int = 1):
        self.status = status
        self.data = data
        self.message = message
        self.latency_ms = 5
        self.attempts = attempts


def test_token_bucket_and_adaptive_aimd() -> None:
    tb = TokenBucket(100.0, 2)
    assert tb.acquire(2.0) == 0.0
    waited = tb.acquire(1.0)
    assert waited >= 0.005

    limiter = AdaptiveRateLimiter(base_qps=10.0, min_qps=2.0, burst=2)
    assert limiter.current_qps == 10.0
    backoff = limiter.on_rate_limited(attempt=0)
    assert backoff > 0
    assert limiter.current_qps == 5.0
    for _ in range(20):
        limiter.on_success()
    assert limiter.current_qps == 10.0


def test_singleflight_coalesces_concurrent_identical_calls() -> None:
    sf = Singleflight()
    calls = 0
    lock = threading.Lock()

    def slow_fn() -> str:
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.04)
        return "shared-payload"

    results: List[Any] = []
    threads = [
        threading.Thread(target=lambda: results.append(sf.do("same-key", slow_fn)))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == 1
    assert len(results) == 5
    assert sum(1 for _, shared in results if shared) == 4
    assert all(val == "shared-payload" for val, _ in results)


def test_expired_cache_is_not_used_when_upstream_quota_exceeded(tmp_path: Path) -> None:
    db_file = str(tmp_path / "cache.db")
    cache = ApiCache(db_file)
    ledger = ProductLedger(str(tmp_path / "ledger.db"))
    settings = Settings(
        baidu_ak="k", baidu_sk="s", request_timeout_s=5.0,
        cache_db=db_file,
        ledger_db=str(tmp_path / "ledger.db"),
    )

    state = {"status": 0}

    class FakeAdapter:
        def reverse_geocode(self, coord, experiment_id=""):
            if state["status"] == 0:
                return _RawResult(0, {"result": {"formatted_address": "北京市东城区王府井大街1号"}})
            return _RawResult(302, {}, message="天配额超限")

    svc = BaiduService(settings, adapter=FakeAdapter(), cache=cache, ledger=ledger)
    pt = Coord(lng=116.418, lat=39.919, crs="BD09")

    place1, _ = svc.resolve_location(pt)
    assert place1.name == "北京市东城区王府井大街1号"

    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE api_cache SET expires_at = '2000-01-01T00:00:00+00:00'")

    state["status"] = 302
    with pytest.raises(ServiceError) as error:
        svc.resolve_location(pt)
    assert error.value.code == "QUOTA_EXCEEDED"
    assert error.value.retryable is False


def test_l2_detour_factor_table_and_estimation() -> None:
    rho_cq = infer_detour_factor(106.577, 29.557)
    rho_bj = infer_detour_factor(116.404, 39.915)
    assert rho_cq == 1.68
    assert rho_bj == 1.42

    l2_res = compute_l2_isochrone(106.577, 29.557, threshold_s=900.0)
    assert l2_res.status == "degraded"
    assert len(l2_res.radii_m) == 8
    assert all(500.0 < r < 800.0 for r in l2_res.radii_m.values())


def test_l2_isochrone_first_and_background_upgrade(tmp_path: Path) -> None:
    db_file = str(tmp_path / "cache.db")
    cache = ApiCache(db_file)
    derived = DerivedCache(str(tmp_path / "derived.db"))
    ledger = ProductLedger(str(tmp_path / "ledger.db"))
    settings = Settings(
        baidu_ak="k", baidu_sk="s", request_timeout_s=5.0,
        cache_db=db_file,
        ledger_db=str(tmp_path / "ledger.db"),
    )

    class FakeMatrixAdapter:
        def routematrix(self, origins, destinations, **kwargs):
            rows = []
            o_lat, o_lng = origins[0]
            for d_lat, d_lng in destinations:
                dist_m = ((d_lat - o_lat) ** 2 + (d_lng - o_lng) ** 2) ** 0.5 * 111320.0
                rows.append({"status": 0, "duration": {"value": int(dist_m * 1.15)}, "distance": {"value": int(dist_m)}})
            return _RawResult(0, {"result": rows})

    b_svc = BaiduService(settings, adapter=FakeMatrixAdapter(), cache=cache, ledger=ledger)
    iso_svc = IsochroneService(b_svc, cache=derived)

    origin = Coord(lng=116.404, lat=39.915, crs="BD09")
    initial = iso_svc.run(origin, threshold_seconds=900.0, l2_first=True)
    assert initial["status"] == "degraded"
    assert initial["backgroundStatus"] == "running"
    task_id = initial["taskId"]

    final_state = None
    for _ in range(40):
        time.sleep(0.02)
        polled = iso_svc.get_task_status(task_id)
        if polled and polled.get("backgroundStatus") != "running":
            final_state = polled
            break

    assert final_state is not None
    assert final_state["backgroundStatus"] in ("completed", "degraded")


def test_corridor_pois_and_matrix_degrade_gracefully_on_midstream_quota_error(tmp_path: Path) -> None:
    db_file = str(tmp_path / "cache.db")
    cache = ApiCache(db_file)
    ledger = ProductLedger(str(tmp_path / "ledger.db"))
    settings = Settings(
        baidu_ak="k", baidu_sk="s", request_timeout_s=5.0,
        cache_db=db_file,
        ledger_db=str(tmp_path / "ledger.db"),
    )

    calls = {"matrix": 0}

    class PartialFailAdapter:
        def routematrix(self, origins, destinations, **kwargs):
            calls["matrix"] += 1
            if calls["matrix"] == 1:
                return _RawResult(0, {"result": [{"status": 0, "duration": {"value": 420}, "distance": {"value": 500}} for _ in destinations]})
            return _RawResult(401, {}, message="当前并发量已经超过约定并发配额")

    svc = BaiduService(
        settings,
        adapter=PartialFailAdapter(),
        cache=cache,
        ledger=ledger,
        rate_limiter=AdaptiveRateLimiter(base_qps=500.0, min_qps=200.0, burst=50),
    )
    o1 = Coord(lng=116.40, lat=39.90, crs="BD09")
    o2 = Coord(lng=116.41, lat=39.91, crs="BD09")
    d_list = [Coord(lng=116.40 + i * 0.001, lat=39.90, crs="BD09") for i in range(30)]

    res = svc.travel_matrix([o1, o2], d_list, trace_id="t-partial")
    ok_cells = [c for c in res["cells"] if c["status"] == "ok"]
    err_cells = [c for c in res["cells"] if c["status"] == "error"]
    assert len(ok_cells) > 0
    assert len(err_cells) > 0
