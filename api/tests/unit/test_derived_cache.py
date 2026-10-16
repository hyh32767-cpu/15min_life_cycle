# -*- coding: utf-8 -*-
from api.app.storage.derived_cache import DerivedCache, derived_key


def _key(**overrides):
    params = {
        "algorithm": "isochrone",
        "algorithm_version": "v1",
        "input_hashes": {"baidu_response": "hash-a"},
        "params": {"thresholdSeconds": 900, "direction": "out", "target": "p1"},
        "assumptions_version": "a1",
        "event_version": "e0",
    }
    params.update(overrides)
    return derived_key(**params)


def test_derived_key_changes_on_any_dependency():
    base = _key()
    assert base == _key()
    assert base != _key(assumptions_version="a2")
    assert base != _key(event_version="e1")
    assert base != _key(algorithm_version="v2")
    assert base != _key(input_hashes={"baidu_response": "hash-b"})
    assert base != _key(params={"thresholdSeconds": 600, "direction": "out", "target": "p1"})


def test_derived_cache_roundtrip(tmp_path):
    cache = DerivedCache(str(tmp_path / "derived.db"))
    key = _key()
    assert cache.get(key) is None
    record = cache.put(key=key, algorithm="isochrone", algorithm_version="v1",
                       dependencies={"baidu_response": "hash-a"},
                       result={"status": "complete", "radii": [1, 2, 3]})
    assert record.result["status"] == "complete"
    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.result["radii"] == [1, 2, 3]
    assert cache.count() == 1


def test_cache_hit_task_id_is_report_retrievable(tmp_path):
    # F66：派生缓存命中生成的新 taskId 登记别名，报告重取可达（不 404）。
    from api.app.services.isochrone_service import IsochroneService
    from api.app.services.baidu_service import BaiduService
    from api.app.storage.api_cache import ApiCache
    from api.app.storage.ledger import ProductLedger
    from api.app.config import Settings
    from api.app.models.common import Coord
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

    cache = DerivedCache(str(tmp_path / "d8.db"))
    baidu = BaiduService(settings, adapter=CachingAdapter(),
                         cache=ApiCache(settings.cache_db),
                         ledger=ProductLedger(settings.ledger_db))
    service = IsochroneService(baidu, cache=cache)
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert first["cacheHit"] is False
    second = service.run(origin, threshold_seconds=900, bearings=[0], max_pairs=64)
    assert second["cacheHit"] is True
    # 新 taskId 经别名索引可重取（payload 换新 taskId，索引指向同派生 key）
    record = cache.get_by_task(second["taskId"])
    assert record is not None
    assert record.result["radiiM"] == first["radiiM"]
