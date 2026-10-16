# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from api.app.dependencies import get_baidu_service
from api.app.main import app
from api.tests.unit.test_baidu_service import FakeAdapter, make_service


def _client_with_fake_service(tmp_path):
    service = make_service(tmp_path, FakeAdapter())
    app.dependency_overrides[get_baidu_service] = lambda: service
    return TestClient(app), service


def test_location_search_endpoint(tmp_path):
    client, _service = _client_with_fake_service(tmp_path)
    try:
        with client:
            resp = client.get("/api/locations/search", params={"q": "测试药店", "city": "北京"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["mode"] == "live"
            assert body["candidates"][0]["uid"] == "uid-1"
            assert body["candidates"][0]["coord"]["crs"] == "BD09"
            assert body["candidates"][0]["naviCoord"]["lat"] == 40.071
    finally:
        app.dependency_overrides.clear()


def test_location_resolve_endpoint_preserves_point_and_validates_coordinates(tmp_path):
    client, _service = _client_with_fake_service(tmp_path)
    try:
        with client:
            coord = {"lng": 116.35, "lat": 40.08, "crs": "BD09"}
            response = client.post("/api/locations/resolve", json={"coord": coord})
            assert response.status_code == 200
            assert response.json()["place"]["coord"] == coord
            assert response.json()["place"]["address"] == "北京市测试路1号"
            assert client.post("/api/locations/resolve", json={"coord": {**coord, "lat": 100}}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_base_map_poi_detail_endpoint_keeps_real_name_and_entry(tmp_path):
    client, service = _client_with_fake_service(tmp_path)
    try:
        with client:
            response = client.get('/api/locations/poi/uid-1')
            assert response.status_code == 200
            assert response.json()['place']['name'] == '测试药店'
            assert response.json()['place']['naviCoord']['lng'] == 116.331
            again = client.get('/api/locations/poi/uid-1')
            assert again.json()['place']['source'] == 'api-cache'
            assert service.adapter.calls.count(('place_detail', 'uid-1')) == 1
    finally:
        app.dependency_overrides.clear()


def test_walking_and_matrix_endpoints(tmp_path):
    client, _service = _client_with_fake_service(tmp_path)
    try:
        with client:
            walking = client.post("/api/routes/walking", json={
                "origin": {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
                "destination": {"lng": 116.34, "lat": 40.08, "crs": "BD09"},
            })
            assert walking.status_code == 200
            body = walking.json()
            assert body["route"]["durationSeconds"] == 575
            assert body["route"]["geometry"][0]["crs"] == "BD09"

            matrix = client.post("/api/travel-matrix", json={
                "origins": [
                    {"lng": 116.33, "lat": 40.07, "crs": "BD09"},
                    {"lng": 116.34, "lat": 40.08, "crs": "BD09"},
                ],
                "destinations": [
                    {"lng": 116.35, "lat": 40.09, "crs": "BD09"},
                    {"lng": 116.36, "lat": 40.10, "crs": "BD09"},
                ],
            })
            assert matrix.status_code == 200
            cells = matrix.json()["cells"]
            assert len(cells) == 4
            assert cells[0]["fromIndex"] == 0 and cells[3]["fromIndex"] == 1
    finally:
        app.dependency_overrides.clear()


def test_invalid_matrix_request_is_rejected(tmp_path):
    client, _service = _client_with_fake_service(tmp_path)
    try:
        with client:
            resp = client.post("/api/travel-matrix", json={"origins": [], "destinations": []})
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        app.dependency_overrides.clear()


def test_corridor_evidence_endpoint_reports_directional_pairs(tmp_path):
    client, _service = _client_with_fake_service(tmp_path)
    try:
        with client:
            resp = client.post("/api/pois/corridor/evidence", json={
                "poi": {"lng": 116.31, "lat": 39.91, "crs": "BD09"},
                "routeGeometry": [
                    {"lng": 116.30, "lat": 39.90, "crs": "BD09"},
                    {"lng": 116.31, "lat": 39.90, "crs": "BD09"},
                ],
                "baselineDurationSeconds": 600,
                "thresholdSeconds": 900,
                "sampleM": 300,
                "maxSamples": 12,
            })
            assert resp.status_code == 200
            body = resp.json()
            assert body["pairsUsed"] == len(body["samples"]) * 2
            assert body["evidence"]["symmetricAssumed"] is False
            assert body["samples"][0]["inboundSeconds"] is not None
            assert body["samples"][0]["outboundSeconds"] is not None
    finally:
        app.dependency_overrides.clear()
