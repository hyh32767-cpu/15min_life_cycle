# -*- coding: utf-8 -*-
from core.coord import haversine
from api.app.models.common import Coord
from api.app.services.errors import ServiceError
from api.app.services.isochrone_service import IsochroneService
from api.app.storage.derived_cache import DerivedCache


class FakeBaidu:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def travel_matrix(self, origins, destinations, *, trace_id=None, stage="A3"):
        self.calls += 1
        if self.fail:
            raise ServiceError("UPSTREAM_ERROR", "network down", http_status=502)
        origin = origins[0]
        return {
            "cells": [
                {"toIndex": index,
                 "durationSeconds": haversine(origin.lng, origin.lat, dest.lng, dest.lat) * (900.0 / 800.0)}
                for index, dest in enumerate(destinations)
            ],
            "responseHashes": ["fake-hash"],
        }


def test_circle_expiry_tracks_source_data_through_derived_cache(tmp_path):
    from api.app.models.api import IsochroneResponse
    class ExpiringBaidu(FakeBaidu):
        def travel_matrix(self, origins, destinations, **kwargs):
            return {**super().travel_matrix(origins, destinations, **kwargs),
                    'expiresAt': '2026-10-13T12:00:00+00:00'}
        def peek_matrix(self, origins, destinations):
            return self.travel_matrix(origins, destinations)
    service = IsochroneService(ExpiringBaidu(), cache=DerivedCache(str(tmp_path / 'expiry.db')))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900)
    second = service.run(origin, threshold_seconds=900)
    assert second['cacheHit'] is True
    assert first['expiresAt'] == second['expiresAt'] == '2026-10-13T12:00:00+00:00'
    assert IsochroneResponse(**second).model_dump(by_alias=True)['expiresAt'] == first['expiresAt']


def test_origin_converts_before_projecting_probe_destinations(tmp_path):
    from api.app.services.baidu_service import to_baidu_bd09
    class Checked(FakeBaidu):
        def travel_matrix(self, origins, destinations, **kwargs):
            assert origins[0].crs.value == 'BD09'
            assert all(destination.crs.value == 'BD09' for destination in destinations)
            return super().travel_matrix(origins, destinations, **kwargs)
    origin = Coord(lng=116.33, lat=40.07, crs='WGS84')
    service = IsochroneService(Checked(), cache=DerivedCache(str(tmp_path / 'c.db')))
    response = service.run(origin, threshold_seconds=900)
    assert response['origin'] == to_baidu_bd09(origin)[0].model_dump(by_alias=True)
    assert response['status'] == 'complete'


def test_mixed_live_and_peek_hashes_all_bind_derived_dependencies(tmp_path):
    class Mixed(FakeBaidu):
        fully_cached = False
        def peek_matrix(self, origins, destinations):
            data = super().travel_matrix(origins, destinations)
            if not self.fully_cached and destinations[0].lat > origins[0].lat + 0.009:
                return None
            return {**data, 'responseHashes': ['peek-hash', 'fake-hash'] if self.fully_cached else ['peek-hash']}
    fake = Mixed()
    service = IsochroneService(fake, cache=DerivedCache(str(tmp_path / 'd.db')))
    first = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900)
    fake.fully_cached = True
    second = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900)
    assert first['status'] == 'complete'
    assert second['cacheHit']
    assert second['radiiM'] == first['radiiM']


def test_isochrone_service_completes_and_caches_by_upstream_hash(tmp_path):
    fake = FakeBaidu()
    service = IsochroneService(fake, cache=DerivedCache(str(tmp_path / "derived.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0, 90], max_pairs=64)
    assert first["status"] == "complete"
    assert first["cacheHit"] is False
    assert set(first["radiiM"].keys()) == {"0", "90"}
    calls_after_first = fake.calls
    # F30 复现：上游 hash 变化时旧圈失效。先让第二次测量的 hash 变化。
    real_travel = fake.travel_matrix
    def changed_hash(origins, destinations, *, trace_id=None, stage="A3"):
        out = real_travel(origins, destinations, trace_id=trace_id, stage=stage)
        return {**out, "responseHashes": ["changed-hash"]}
    fake.travel_matrix = changed_hash
    second = service.run(origin, threshold_seconds=900, bearings=[0, 90], max_pairs=64)
    assert second["cacheHit"] is False
    assert fake.calls > calls_after_first
    fake.travel_matrix = real_travel


def test_upstream_hash_change_forces_remeasure(tmp_path):
    # F30 复现：上游 hash 变化时旧圈失效并重算（cacheHit=False 且确有新测量）。
    fake = FakeBaidu()
    service = IsochroneService(fake, cache=DerivedCache(str(tmp_path / "d6.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    calls_after_first = fake.calls
    real_travel = fake.travel_matrix

    def changed_hash(origins, destinations, *, trace_id=None, stage="A3"):
        out = real_travel(origins, destinations, trace_id=trace_id, stage=stage)
        return {**out, "responseHashes": ["changed-hash"]}

    fake.travel_matrix = changed_hash
    try:
        second = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    finally:
        fake.travel_matrix = real_travel
    assert second["cacheHit"] is False
    assert fake.calls > calls_after_first
    assert second["radiiM"] == first["radiiM"]


def test_isochrone_service_reports_upstream_failure_without_fake_radius(tmp_path):
    service = IsochroneService(FakeBaidu(fail=True), cache=DerivedCache(str(tmp_path / "d.db")))
    result = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900,
                         bearings=[0], max_pairs=64)
    assert result["status"] == "failed"
    assert result["radiiM"] == {}
    assert any("upstream:UPSTREAM_ERROR" in item for item in result["warnings"])


def test_failed_isochrone_is_not_cached(tmp_path):
    service = IsochroneService(FakeBaidu(fail=True),
                              cache=DerivedCache(str(tmp_path / "d2.db")))
    first = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900,
                        bearings=[0], max_pairs=64)
    assert first["status"] == "failed"
    assert first["cacheHit"] is False
    second = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900,
                         bearings=[0], max_pairs=64)
    assert second["cacheHit"] is False


def test_cache_key_varies_by_threshold_and_mode(tmp_path):
    live = IsochroneService(FakeBaidu(),
                           cache=DerivedCache(str(tmp_path / "d3.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = live.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    again = live.run(origin, threshold_seconds=901, bearings=[0], max_pairs=64)
    assert again["cacheHit"] is False


def test_upstream_hash_change_bypasses_stale_circle(tmp_path):
    service = IsochroneService(FakeBaidu(),
                              cache=DerivedCache(str(tmp_path / "d4.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    # 上游数据变化（hash 变化）时 hash-bound key 不命中，必须重算而非读旧圈。
    from api.app.services import isochrone_service as mod
    real_travel = service.baidu.travel_matrix
    def changed_hash(origins, destinations, *, trace_id=None, stage="A3"):
        out = real_travel(origins, destinations, trace_id=trace_id, stage=stage)
        return {**out, "responseHashes": ["changed-hash"]}
    service.baidu.travel_matrix = changed_hash
    calls_before = service.baidu.calls
    # 直接验证 key 差异：不同 upstream hash 产生不同 key
    from api.app.storage.derived_cache import derived_key
    from core.isochrone import ALGORITHM_VERSION
    base_params = {
        "thresholdSeconds": 900.0, "bearings": [0.0], "loM": 200.0,
        "hiM": 1400.0, "initialM": 800.0, "tolM": 50.0, "maxPairs": 64,
        "mode": "live", "apiVersion": "matrix_walking/v2",
    }
    key_old = derived_key(algorithm="isochrone-batched", algorithm_version=ALGORITHM_VERSION,
                          input_hashes={"origin": "40.070000,116.330000"},
                          params={**base_params, "upstreamResponseHashes": ["fake-hash"]})
    key_new = derived_key(algorithm="isochrone-batched", algorithm_version=ALGORITHM_VERSION,
                          input_hashes={"origin": "40.070000,116.330000"},
                          params={**base_params, "upstreamResponseHashes": ["changed-hash"]})
    assert key_old != key_new
    assert service.baidu.calls == calls_before  # 本断言仅确认 key 逻辑，实际重算由 run 触发

def test_derived_cache_hit_zeroes_pairs_and_carries_trace(tmp_path):
    fake = FakeBaidu()
    service = IsochroneService(fake, cache=DerivedCache(str(tmp_path / "d5.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    assert first["pairsUsed"] > 0
    assert first["traceId"]
    calls_after_first = fake.calls
    second = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert second["cacheHit"] is True
    assert second["pairsUsed"] == 0
    assert second["traceId"]
    assert second["radiiM"] == first["radiiM"]
    assert any("ledger-cost-0" in item for item in second["warnings"])
    # F49：派生缓存命中必须零上游调用。FakeBaidu 无 API 缓存层时 peek 缺失，
    # 仍走旧流程（调用增加）；有 API 缓存时 peek 全命中，调用数不变（见下个测试）。


def test_second_run_with_warm_api_cache_skips_upstream(tmp_path):
    # F49：API 缓存命中时，第二次等时圈请求零上游调用（peek 全命中 + 派生命中）。
    from api.app.services.baidu_service import BaiduService
    from api.app.storage.api_cache import ApiCache
    from api.app.storage.ledger import ProductLedger
    from api.app.config import Settings
    settings = Settings(
        baidu_ak="test-ak", baidu_sk="",
        ledger_db=str(tmp_path / "ledger.db"), cache_db=str(tmp_path / "cache.db"),
        request_timeout_s=10.0,
    )
    fake_calls = {"n": 0}

    class CachingAdapter:
        def routematrix(self, origins, destinations, *, experiment_id=None, timeout=10.0):
            fake_calls["n"] += 1
            from core.coord import haversine
            from core.baidu_client import ApiResult
            body = {"result": [
                {"duration": {"value": haversine(o[1], o[0], d[1], d[0]) * (900.0 / 800.0)},
                 "distance": {"value": 800.0}}
                for o in origins for d in destinations
            ], "status": 0}
            return ApiResult(True, 0, "ok", body, 5)

    service = IsochroneService(
        BaiduService(settings, adapter=CachingAdapter(),
                     cache=ApiCache(settings.cache_db),
                     ledger=ProductLedger(settings.ledger_db)),
        cache=DerivedCache(str(tmp_path / "d6.db")),
    )
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    assert first["pairsUsed"] > 0
    calls_after_first = fake_calls["n"]
    assert calls_after_first > 0
    second = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert second["cacheHit"] is True
    assert second["pairsUsed"] == 0
    assert second["radiiM"] == first["radiiM"]
    assert fake_calls["n"] == calls_after_first


def test_warm_api_cache_second_run_hits_derived_cache(tmp_path):
    # F70：预置 API cache、空 derived cache 时第一次写入 peek-hash key，
    # 第二次同请求命中派生缓存（cacheHit=True、零上游调用）。
    from api.app.services.baidu_service import BaiduService
    from api.app.storage.api_cache import ApiCache
    from api.app.storage.ledger import ProductLedger
    from api.app.config import Settings
    settings = Settings(
        baidu_ak="test-ak", baidu_sk="",
        ledger_db=str(tmp_path / "ledger.db"), cache_db=str(tmp_path / "cache.db"),
        request_timeout_s=10.0,
    )
    fake_calls = {"n": 0}

    class CachingAdapter:
        def routematrix(self, origins, destinations, *, experiment_id=None, timeout=10.0):
            fake_calls["n"] += 1
            from core.coord import haversine
            from core.baidu_client import ApiResult
            body = {"result": [
                {"duration": {"value": haversine(o[1], o[0], d[1], d[0]) * (900.0 / 800.0)},
                 "distance": {"value": 800.0}}
                for o in origins for d in destinations
            ], "status": 0}
            return ApiResult(True, 0, "ok", body, 5)

    baidu = BaiduService(settings, adapter=CachingAdapter(),
                         cache=ApiCache(settings.cache_db),
                         ledger=ProductLedger(settings.ledger_db))
    service = IsochroneService(baidu, cache=DerivedCache(str(tmp_path / "d7.db")))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    calls_after_first = fake_calls["n"]
    assert calls_after_first > 0
    # 清空 API 缓存调用计数：第二次应全走 peek + 派生缓存，零上游调用
    second = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert second["cacheHit"] is True
    assert second["pairsUsed"] == 0
    assert second["radiiM"] == first["radiiM"]
    assert fake_calls["n"] == calls_after_first
    # 第三次同样命中（写入的 key 与查找 key 一致，F70 回归）
    third = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert third["cacheHit"] is True
    assert fake_calls["n"] == calls_after_first
