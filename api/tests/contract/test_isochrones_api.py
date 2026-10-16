# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from api.app.dependencies import get_isochrone_service
from api.app.main import app


class FakeIsochroneService:
    def run(self, origin, **kwargs):
        return {
            "taskId": "task-1",
            "status": "complete",
            "placeId": kwargs.get("place_id"),
            "thresholdSeconds": kwargs["threshold_seconds"],
            "radiiM": {"0": 800.0, "90": 790.0},
            "failedBearings": [],
            "skippedBearings": [],
            "algorithmVersion": "m2-ray-bisect-v1",
            "warnings": [],
            "cacheHit": False,
            "pairsUsed": 4,
            "traceId": "trace-1",
        }


def test_isochrone_api_returns_radii_and_sources():
    app.dependency_overrides[get_isochrone_service] = lambda: FakeIsochroneService()
    try:
        with TestClient(app) as client:
            resp = client.post("/api/isochrones", json={
                "placeId": "p1",
                "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
                "thresholdSeconds": 900,
                "bearings": [0, 90],
                "maxPairs": 64,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "complete"
            assert body["taskId"] == "task-1"
            assert body["radiiM"]["0"] == 800.0
            assert body["cacheHit"] is False
    finally:
        app.dependency_overrides.clear()


def test_isochrone_api_rejects_missing_origin():
    app.dependency_overrides[get_isochrone_service] = lambda: FakeIsochroneService()
    try:
        with TestClient(app) as client:
            resp = client.post("/api/isochrones", json={"thresholdSeconds": 900})
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


def test_isochrone_rejects_inverted_range(hermetic_app):
    # F68：422 由请求校验产生，与 AK 无关；经 hermetic_app 可过。
    client, _service = hermetic_app
    with client:
        resp = client.post("/api/isochrones", json={
            "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
            "thresholdSeconds": 900,
            "loM": 1400, "hiM": 200,
        })
        assert resp.status_code == 422


def test_isochrone_response_carries_mode_source_origin_report(hermetic_app):
    # F56：响应自带 mode/sourceKind/origin/report；面积为近似值声明。
    # F68：经 hermetic_app（FakeAdapter），无 AK/无网络可过。
    client, _service = hermetic_app
    payload = {
        "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
        "thresholdSeconds": 900,
        "bearings": [0, 90, 180, 270],
        "maxPairs": 64,
    }
    with client:
        resp = client.post("/api/isochrones", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "live"
        assert body["sourceKind"] in {"derived", "live-api", "api-cache", "mixed"}
        assert body["origin"] == {"lng": 116.33, "lat": 40.07, "crs": "BD09"}
        report = body["report"]
        assert report["thresholdSeconds"] == 900
        assert report["effectiveBearings"] >= 0
        assert "approxNote" in report and "近似" in report["approxNote"]


def test_isochrone_pois_filters_by_directed_matrix(hermetic_app):
    # F57：区域召回后用起点->POI 有向矩阵过滤；可达按 walkSeconds 排序，超时/无路进 unreachable。
    # F68：经 hermetic_app（FakeAdapter），无 AK/无网络可过。
    client, _service = hermetic_app
    payload = {
        "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
        "thresholdSeconds": 900,
        "queryTerms": ["药店"],
        "searchRadiusM": 1000,
        "maxPagesPerTerm": 1,
    }
    with client:
        resp = client.post("/api/isochrones/pois", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "live"
        assert body["pairsUsed"] >= 0
        for row in body["reachable"]:
            assert row["walkSeconds"] is not None and row["walkSeconds"] <= 900
        for row in body["unreachable"]:
            assert row["reason"] in {"no_route", "over_threshold"}
        walks = [row["walkSeconds"] for row in body["reachable"]]
        assert walks == sorted(walks)


def test_isochrone_report_median_averages_even_bearings():
    # F67：偶数条半径取两中位数平均（单元级，不依赖百度场）。
    from api.app.services.isochrone_service import _isochrone_report
    from api.app.models.common import Coord

    class _R:
        status = 'complete'
        radii_m = {0.0: 600.0, 90.0: 800.0, 180.0: 1000.0, 270.0: 1200.0}
        failed_bearings = []
        skipped_bearings = []
        algorithm_version = "m2-ray-bisect-v1"
        pairs_used = 4

    report = _isochrone_report(_R(), threshold_seconds=900.0,
                               origin=Coord(lng=116.33, lat=40.07))
    assert report["medianRadiusM"] == (800.0 + 1000.0) / 2.0
    assert report["maxRadiusM"] == 1200.0
    assert report["minRadiusM"] == 600.0


def test_isochrone_pois_reports_truncation(hermetic_app):
    # F67：圈内 POI 超 maxUnique 时暴露 truncated/truncationReason，不谎称全量。
    client, _service = hermetic_app
    with client:
        resp = client.post("/api/isochrones/pois", json={
            "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
            "thresholdSeconds": 900,
            "queryTerms": ["药店"],
            "searchRadiusM": 1000,
            "maxPagesPerTerm": 1,
            "maxUnique": 1,
        })
        assert resp.status_code == 200
        body = resp.json()
        if body["retrieval"]["uniqueCount"] > 1:
            assert body["retrieval"]["truncated"] is True
            assert body["retrieval"]["truncationReason"] == "max_unique"
