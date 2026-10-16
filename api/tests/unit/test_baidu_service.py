# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from api.app.config import Settings
from core.baidu_client import ApiResult
from api.app.services.baidu_service import BaiduService
from api.app.services.errors import ServiceError
from api.app.storage.api_cache import ApiCache, request_hash
from api.app.storage.ledger import ProductLedger


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def reverse_geocode(self, location, *, experiment_id="api"):
        self.calls.append(("reverse_geocode", location))
        return ApiResult(True, 0, "ok", {"status": 0, "result": {
            "formatted_address": "北京市测试路1号",
            "location": {"lng": 116.0, "lat": 40.0},
        }}, latency_ms=10)

    def place_search(self, query, *, region=None, location=None, radius=None,
                     page_num=0, page_size=20, experiment_id="api"):
        self.calls.append(("place_search", query))
        return ApiResult(True, 0, "ok", {
            "status": 0,
            "message": "ok",
            "results": [{
                "uid": "uid-1",
                "name": "测试药店",
                "address": "北京市昌平区测试路1号",
                "location": {"lat": 40.07, "lng": 116.33},
                "detail_info": {"navi_location": {"lat": 40.071, "lng": 116.331},
                                "shop_hours": "08:00-22:00"},
            }],
        }, latency_ms=12)

    def geocode(self, address, *, city=None, experiment_id="api"):
        self.calls.append(("geocode", address))
        return ApiResult(True, 0, "ok", {
            "status": 0,
            "result": {"location": {"lat": 40.07, "lng": 116.33}},
        }, latency_ms=12)

    def place_detail(self, uid, *, experiment_id="api"):
        self.calls.append(("place_detail", uid))
        return ApiResult(True, 0, "ok", {
            "status": 0,
            "results": [{
                "uid": uid,
                "name": "测试药店",
                "address": "北京市昌平区测试路1号",
                "location": {"lat": 40.07, "lng": 116.33},
                "detail_info": {
                    "navi_location": {"lat": 40.071, "lng": 116.331},
                    "shop_hours": "",
                    "status": "1",
                },
            }],
        }, latency_ms=15)

    def walking(self, origin, destination, *, experiment_id="api"):
        self.calls.append(("walking", origin, destination))
        return ApiResult(True, 0, "ok", {
            "status": 0,
            "result": {"routes": [{
                "duration": 575,
                "distance": 674,
                "originLocation": {"lat": origin[0], "lng": origin[1]},
                "destinationLocation": {"lat": destination[0], "lng": destination[1]},
                "steps": [{"path": "116.3309,40.0703;116.3310,40.0702",
                           "distance": 674, "duration": 575, "instructions": "步行"}],
            }]},
        }, latency_ms=18)

    def routematrix(self, origins, destinations, *, experiment_id="api"):
        self.calls.append(("routematrix", len(origins), len(destinations)))
        items = []
        for i, _o in enumerate(origins):
            for j, _d in enumerate(destinations):
                items.append({
                    "duration": {"value": 568 + i + j},
                    "distance": {"value": 665 + i + j},
                })
        return ApiResult(True, 0, "ok", {"status": 0, "result": items}, latency_ms=25)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        baidu_ak="fake-ak",
        baidu_sk="",
        ledger_db=str(tmp_path / "ledger.db"),
        cache_db=str(tmp_path / "cache.db"),
        request_timeout_s=10.0,
    )


def make_service(tmp_path: Path, adapter=None) -> BaiduService:
    settings = make_settings(tmp_path)
    return BaiduService(settings, adapter=adapter or FakeAdapter(),
                        cache=ApiCache(settings.cache_db),
                        ledger=ProductLedger(settings.ledger_db))


def test_life_circle_cache_metadata_preserves_original_expiry(tmp_path):
    from api.app.models.common import Coord
    from api.app.models.api import CorridorResponse, TravelMatrixResponse
    service = make_service(tmp_path)
    origin = Coord(lng=116.33, lat=40.07, crs="BD09")
    first = service.corridor_pois([origin, origin], ['药店$药房'], max_pages_per_window=1)
    second = service.corridor_pois([origin, origin], ['药店$药房'], max_pages_per_window=1)
    assert first['cacheHit'] is False
    assert second['cacheHit'] is True
    assert first['expiresAt'] == second['expiresAt'] and first['expiresAt']
    assert CorridorResponse(**second).model_dump(by_alias=True)['expiresAt'] == first['expiresAt']
    destination = Coord(lng=116.34, lat=40.08, crs="BD09")
    matrix = service.travel_matrix([origin], [destination])
    repeated = service.travel_matrix([origin], [destination])
    assert repeated['cacheHit'] is True
    assert matrix['expiresAt'] == repeated['expiresAt'] and matrix['expiresAt']
    assert TravelMatrixResponse(**repeated).model_dump(by_alias=True)['expiresAt'] == matrix['expiresAt']


def test_reverse_location_keeps_picked_coordinate_and_uses_real_cache(tmp_path):
    from api.app.models.common import Coord
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    point = Coord(lng=116.35, lat=40.08, crs="BD09")
    place, trace = service.resolve_location(point)
    assert place.coord == point  # 不吸附到响应中的附近地物坐标
    assert place.name == "北京市测试路1号"
    assert place.source.value == "live-api"
    cached, _ = service.resolve_location(point)
    assert cached.source.value == "api-cache"
    assert adapter.calls == [("reverse_geocode", (40.08, 116.35))]
    assert trace


def test_reverse_location_converts_coordinate_and_rejects_empty_address(tmp_path):
    from api.app.models.common import Coord
    from api.app.services.baidu_service import to_baidu_bd09
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    raw = Coord(lng=116.35, lat=40.08, crs="WGS84")
    expected, _ = to_baidu_bd09(raw)
    place, _ = service.resolve_location(raw)
    assert place.coord == expected
    assert adapter.calls[-1] == ("reverse_geocode", (expected.lat, expected.lng))

    adapter.reverse_geocode = lambda *a, **kw: ApiResult(True, 0, "ok", {"result": {}})
    with pytest.raises(ServiceError) as error:
        service.resolve_location(Coord(lng=116.4, lat=40.08, crs="BD09"))
    assert error.value.code == "NO_RESULT"


def test_location_search_parses_candidates_and_uses_cache(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    candidates, trace = service.search_locations("测试药店", city="北京")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.uid == "uid-1"
    assert candidate.coord.crs.value == "BD09"
    assert candidate.navi_coord is not None
    assert candidate.source.value == "live-api"

    service.ledger.summary(trace)
    assert adapter.calls.count(("place_search", "测试药店")) == 1
    candidates2, _ = service.search_locations("测试药店", city="北京")
    assert len(candidates2) == 1
    assert candidates2[0].source.value == "api-cache"
    assert adapter.calls.count(("place_search", "测试药店")) == 1
    summary = service.ledger.summary()
    assert summary.live_requests == 1
    assert summary.cache_hits == 1


def test_walking_route_geometry_and_metrics_come_from_same_response(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    from api.app.models.common import Coord

    result = service.walking_route(Coord(lng=116.33, lat=40.07),
                                   Coord(lng=116.34, lat=40.08))
    route = result["route"]
    assert route["durationSeconds"] == 575
    assert route["distanceM"] == 674
    assert route["geometry"][0] == {"lng": 116.3309, "lat": 40.0703, "crs": "BD09"}
    assert route["steps"][0]["instructions"] == "步行"
    assert adapter.calls[-1][0] == "walking"


def test_travel_matrix_keeps_origin_major_order_and_direction(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    from api.app.models.common import Coord

    result = service.travel_matrix(
        [Coord(lng=116.33, lat=40.07), Coord(lng=116.34, lat=40.08)],
        [Coord(lng=116.35, lat=40.09), Coord(lng=116.36, lat=40.10)],
    )
    cells = result["cells"]
    assert len(cells) == 4
    assert cells[0] == {
        "fromIndex": 0, "toIndex": 0, "durationSeconds": 568,
        "distanceM": 665, "status": "ok", "sourceKind": "live-api",
    }
    assert cells[1]["toIndex"] == 1
    assert cells[2]["fromIndex"] == 1 and cells[2]["toIndex"] == 0
    assert cells[2]["durationSeconds"] == 569


def test_travel_matrix_stage_threads_to_ledger(tmp_path):
    from api.app.models.common import Coord

    service = make_service(tmp_path, FakeAdapter())
    origins = [Coord(lng=116.33, lat=40.07)]
    destinations = [Coord(lng=116.34, lat=40.08)]
    service.travel_matrix(origins, destinations)
    plan_rows = service.ledger.summary(group_by="stage").by_stage
    assert {item.key for item in plan_rows} == {"A3"}
    service.travel_matrix(origins, destinations, stage="isochrone")
    by_stage = {item.key: item for item in service.ledger.summary(group_by="stage").by_stage}
    assert by_stage["isochrone"].rows == 1
    assert by_stage["A3"].rows == 1


def test_live_cache_hit_avoids_second_upstream_call(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    candidates, _trace = service.search_locations("测试药店", city="北京")
    assert candidates[0].name == "测试药店"
    assert candidates[0].source.value == "live-api"
    calls_after_first = len(adapter.calls)
    candidates, _trace = service.search_locations("测试药店", city="北京")
    assert candidates[0].source.value == "api-cache"
    assert len(adapter.calls) == calls_after_first
    summary = service.ledger.summary()
    assert summary.cache_hits == 1 and summary.live_requests == 1


def test_place_detail_empty_hours_stays_unknown(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    place, _trace = service.place_detail("uid-1")
    assert place.uid == "uid-1"
    assert place.shop_hours is None
    assert place.navi_coord is not None
    assert place.status == "1"


def test_corridor_evidence_separates_inbound_and_outbound(tmp_path):
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    from api.app.models.common import Coord

    poi = Coord(lng=116.31, lat=39.91)
    geometry = [
        Coord(lng=116.30, lat=39.90),
        Coord(lng=116.31, lat=39.90),
    ]
    result = service.corridor_evidence(
        poi, geometry, baseline_duration_seconds=600, threshold_seconds=900,
        sample_m=300, max_samples=12,
    )
    assert result["pairsUsed"] == len(result["samples"]) * 2
    assert result["evidence"]["symmetricAssumed"] is False
    assert result["samples"][0]["inboundSeconds"] is not None
    assert result["samples"][0]["outboundSeconds"] is not None


def test_travel_matrix_chunks_over_50_pairs_and_fills_grid(tmp_path):
    from api.app.models.common import Coord
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter=adapter)
    origins = [Coord(lng=116.3 + i * 0.001, lat=40.0, crs="BD09") for i in range(17)]
    destinations = [Coord(lng=116.3 + j * 0.001, lat=40.01, crs="BD09") for j in range(17)]
    result = service.travel_matrix(origins, destinations)
    assert len(result["cells"]) == 17 * 17
    batches = [call for call in adapter.calls if call[0] == "routematrix"]
    assert batches, "矩阵未请求百度接口"
    for _name, n_o, n_d in batches:
        assert n_o * n_d <= 50
    assert len(batches) > 1
    by_index = {(cell["fromIndex"], cell["toIndex"]): cell for cell in result["cells"]}
    assert len(by_index) == 17 * 17
    assert all(cell["status"] == "ok" for cell in result["cells"])


def test_travel_matrix_short_response_fills_error_not_silent(tmp_path):
    from api.app.models.common import Coord
    adapter = FakeAdapter()
    orig = adapter.routematrix
    def short(origins, destinations, *, experiment_id="api"):
        result = orig(origins, destinations, experiment_id=experiment_id)
        result.data["result"] = result.data["result"][:-1]
        return result
    adapter.routematrix = short
    service = make_service(tmp_path, adapter=adapter)
    origins = [Coord(lng=116.3, lat=40.0, crs="BD09")]
    destinations = [Coord(lng=116.3, lat=40.01, crs="BD09"),
                    Coord(lng=116.31, lat=40.01, crs="BD09")]
    result = service.travel_matrix(origins, destinations)
    assert len(result["cells"]) == 2
    assert result["cells"][-1]["status"] == "error"
    assert result["cells"][-1]["durationSeconds"] is None


def test_service_builds_configured_live_adapter(tmp_path):
    from api.app.services.baidu_service import BaiduService as RealService
    settings = make_settings(tmp_path)
    service = RealService(settings)
    assert service.adapter.configured is True


def test_normalize_hours_groups_periods_by_day():
    # F43：regular_open_hour.periods 按 day 分组归一化；跨午夜保留 closeDay。
    from api.app.services.baidu_service import BaiduService
    detail = {"regular_open_hour": {"periods": [
        {"open": {"day": 1, "hour": 7, "minute": 0}, "close": {"day": 2, "hour": 0, "minute": 0}},
        {"open": {"day": 1, "hour": 13, "minute": 30}, "close": {"day": 1, "hour": 17, "minute": 0}},
        {"open": {"day": 0, "hour": 0, "minute": 0}},
    ]}, "shop_hours": "07:00-24:00"}
    shop, structured = BaiduService._normalize_hours(detail)
    assert shop == "07:00-24:00"
    assert structured is not None
    day1 = [w for w in structured if w["day"] == 1]
    assert len(day1) == 2
    assert day1[0]["closeDay"] == 2
    # 未返回 close 不推断全天开放
    day0 = [w for w in structured if w["day"] == 0]
    assert not day0


def test_normalize_hours_empty_stays_unknown():
    from api.app.services.baidu_service import BaiduService
    shop, structured = BaiduService._normalize_hours({})
    assert shop is None and structured is None


def test_wgs84_origin_converted_to_bd09_before_request(tmp_path):
    # F61：WGS84 自定位经唯一出口转 BD09 后再发请求、再算缓存 key；响应带转换警告。
    from api.app.models.common import Coord
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    origin = Coord(lng=116.33, lat=40.07, crs="WGS84")
    dest = Coord(lng=116.34, lat=40.08, crs="BD09")
    result = service.walking_route(origin, dest)
    assert any("WGS84->BD09" in w for w in result["warnings"])
    sent_origin = adapter.calls[-1][1]
    from core.coord import wgs84_to_bd09
    expect_lng, expect_lat = wgs84_to_bd09(116.33, 40.07)
    assert abs(sent_origin[0] - expect_lat) < 1e-9
    assert abs(sent_origin[1] - expect_lng) < 1e-9
    # 第二次同坐标命中缓存，不再发新请求
    calls = len(adapter.calls)
    service.walking_route(origin, dest)
    assert len(adapter.calls) == calls


def test_unknown_crs_rejected_not_silently_bd09(tmp_path):
    # F61：未知坐标系直接 422，不静默当 BD09 发请求。
    from api.app.models.common import Coord
    from api.app.services.errors import ServiceError
    service = make_service(tmp_path, FakeAdapter())
    bad = Coord.model_construct(lng=116.33, lat=40.07, crs="XYZ")
    with pytest.raises(ServiceError) as exc:
        service.walking_route(bad, bad)
    assert exc.value.code == "VALIDATION_ERROR"


def test_rate_limited_response_cools_down_then_succeeds(tmp_path):
    # F69：401 响应走退避（3s/10s 两次），成功后不再抛；账本记录退避行。
    from core.baidu_client import ApiResult
    from api.app.models.common import Coord
    calls = {"n": 0}

    class FlakyAdapter(FakeAdapter):
        def routematrix(self, origins, destinations, *, experiment_id="api"):
            calls["n"] += 1
            if calls["n"] == 1:
                return ApiResult(True, 401, "rate limited", {"status": 401}, latency_ms=5)
            return super().routematrix(origins, destinations, experiment_id=experiment_id)

    service = make_service(tmp_path, FlakyAdapter())
    origins = [Coord(lng=116.3, lat=40.0)]
    destinations = [Coord(lng=116.3, lat=40.01)]
    with pytest.raises(ServiceError) as error:
        service.travel_matrix(origins, destinations)
    assert error.value.code == 'RATE_LIMITED'
    assert error.value.retry_after >= 14
    service._cooldowns.clear()  # 模拟冷却结束，第二次显式调用才请求上游。
    result = service.travel_matrix(origins, destinations)
    assert calls["n"] == 2
    assert result["cells"][0]["status"] == "ok"
    summary = service.ledger.summary()
    assert summary.rows >= 2  # 退避行 + 成功行


def test_persistent_401_raises_rate_limited(tmp_path):
    # F69：连续 401 用尽退避后按原语义抛 RATE_LIMITED。
    from core.baidu_client import ApiResult
    from api.app.models.common import Coord
    from api.app.services.errors import ServiceError
    calls = {"n": 0}

    class AlwaysLimited(FakeAdapter):
        def routematrix(self, origins, destinations, *, experiment_id="api"):
            calls["n"] += 1
            return ApiResult(True, 401, "rate limited", {"status": 401}, latency_ms=5)

    service = make_service(tmp_path, AlwaysLimited())
    with pytest.raises(ServiceError) as exc:
        service.travel_matrix([Coord(lng=116.3, lat=40.0)], [Coord(lng=116.3, lat=40.01)])
    assert exc.value.code == "RATE_LIMITED"
    assert calls["n"] == 1  # 401立即进入冷却，不同步重试


def test_matrix_partial_cache_marks_mixed_source(tmp_path):
    # F65：多批次部分命中缓存时顶层 sourceKind 为 mixed，各 cell 保留真实来源。
    from api.app.models.common import Coord
    adapter = FakeAdapter()
    service = make_service(tmp_path, adapter)
    origins = [Coord(lng=116.3 + i * 0.01, lat=40.0) for i in range(6)]
    destinations = [Coord(lng=116.3 + j * 0.01, lat=40.01) for j in range(10)]
    # 第一批 5 行先请求一次（写入缓存），再整体请求 6 行：第一批命中、第二批实时
    service.travel_matrix(origins[:5], destinations)
    calls_after_first = len(adapter.calls)
    result = service.travel_matrix(origins, destinations)
    kinds = {cell["sourceKind"] for cell in result["cells"]}
    assert kinds == {"api-cache", "live-api"}
    assert result["sourceKind"] == "mixed"
    assert result["cacheHit"] is False
    assert any("混合" in w for w in result["warnings"])
    assert len(adapter.calls) > calls_after_first
