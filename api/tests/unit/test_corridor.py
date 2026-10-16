# -*- coding: utf-8 -*-
from core.baidu_client import ApiResult
from api.app.models.common import Coord
from api.app.services.corridor import (point_to_polyline_m, polyline_length_m,
                                       sample_centers)
from api.tests.unit.test_baidu_service import make_service


def test_sample_centers_covers_start_end_and_spacing():
    route = [(116.30, 39.90), (116.31, 39.90)]  # 约 850m
    length = polyline_length_m(route)
    centers = sample_centers(route, spacing_m=300, radius_m=300)
    assert centers[0] == route[0]
    assert centers[-1] == route[-1]
    assert 3 <= len(centers) <= 6


def test_point_to_polyline_distance():
    route = [(116.30, 39.90), (116.31, 39.90)]
    # 路线中点向北约 100m
    off = (116.305, 39.9009)
    distance = point_to_polyline_m(off, route)
    assert 80 <= distance <= 120
    assert point_to_polyline_m((116.305, 39.90), route) < 5


class FakeCorridorAdapter:
    def __init__(self):
        self.search_calls = []

    def place_search(self, query, *, region=None, location=None, radius=None,
                     page_num=0, page_size=20, experiment_id="api"):
        self.search_calls.append((query, page_num))
        if page_num == 0:
            return ApiResult(True, 0, "ok", {
                "status": 0,
                "results": [{
                    "uid": "poi-corridor-1",
                    "name": "走廊测试药店",
                    "address": "测试路",
                    "location": {"lat": 39.9001, "lng": 116.3005},
                } for _ in range(20)],
                "total": 20,
            })
        return ApiResult(True, 0, "ok", {"status": 0, "results": [], "total": 20})


def test_corridor_retrieval_paginates_and_dedupes(tmp_path):
    adapter = FakeCorridorAdapter()
    service = make_service(tmp_path, adapter)
    route = [
        Coord(lng=116.3000, lat=39.9000),
        Coord(lng=116.3010, lat=39.9000),
    ]
    result = service.corridor_pois(
        route, ["药店"], category="药店",
        corridor_buffer_m=1500, window_radius_m=1000,
        window_spacing_m=1000, max_pages_per_window=3,
    )
    retrieval = result["retrieval"]
    assert retrieval["windows"] == 2
    assert retrieval["pages"] == 4
    assert retrieval["rawCount"] == 40
    assert retrieval["uniqueCount"] == 1
    assert retrieval["truncated"] is False
    assert len(result["pois"]) == 1
    assert result["pois"][0]["place"]["uid"] == "poi-corridor-1"
    assert result["pois"][0]["distanceToRouteM"] < 200
