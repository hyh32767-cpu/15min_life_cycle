# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from api.app.main import app


def _client() -> TestClient:
    return TestClient(app)


def _base_request() -> dict:
    return {
        "startId": "S",
        "endId": "H",
        "departureSeconds": 0,
        "deadlineSeconds": 1000,
        "tasks": [
            {"id": "A", "options": [{"placeId": "A", "serviceSeconds": 100,
                                     "serviceSourceKind": "user-input"}]},
            {"id": "B", "options": [{"placeId": "B", "serviceSeconds": 100,
                                     "serviceSourceKind": "user-input"}],
             "precedenceIds": ["A"]},
        ],
        "travelTimes": [
            {"from": "S", "to": "A", "durationSeconds": 100, "distanceM": 120, "sourceKind": "api-cache"},
            {"from": "A", "to": "B", "durationSeconds": 80, "distanceM": 90, "sourceKind": "api-cache"},
            {"from": "B", "to": "H", "durationSeconds": 100, "distanceM": 110, "sourceKind": "api-cache"},
            {"from": "S", "to": "B", "durationSeconds": 160, "distanceM": 180, "sourceKind": "api-cache"},
            {"from": "B", "to": "A", "durationSeconds": 80, "distanceM": 90, "sourceKind": "api-cache"},
            {"from": "A", "to": "H", "durationSeconds": 120, "distanceM": 130, "sourceKind": "api-cache"},
        ],
        "preference": "fastest",
    }


def test_plan_api_returns_ordered_alternative_with_sources():
    with _client() as client:
        resp = client.post("/api/plans", json=_base_request())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        best = body["alternatives"][0]
        assert [stop["placeId"] for stop in best["stops"]] == ["A", "B"]
        assert best["finishSeconds"] == 480
        assert all(stop["travelSourceKind"] == "api-cache" for stop in best["stops"])
        assert all(stop["serviceSourceKind"] == "user-input" for stop in best["stops"])
        kinds = [item["kind"] for item in best["timeline"]]
        assert "returnTravel" in kinds
        assert "deadline" in kinds
        assert best["returnTravelSourceKind"] == "api-cache"
        assert best["slackSeconds"] == 520


def test_reordered_waypoints_override_cheaper_order_and_keep_last_return_leg():
    request = _base_request()
    request['tasks'][0]['precedenceIds'] = ['B']
    request['tasks'][1]['precedenceIds'] = []
    with _client() as client:
        response = client.post('/api/plans', json=request)
        assert response.status_code == 200
        best = response.json()['alternatives'][0]
        assert [stop['placeId'] for stop in best['stops']] == ['B', 'A']
        assert best['finishSeconds'] == 560
        assert best['returnTravelSeconds'] == 120


def test_plan_api_missing_route_is_infeasible_without_fake_leg():
    payload = _base_request()
    payload["travelTimes"] = [cell for cell in payload["travelTimes"]
                              if not (cell["from"] == "S" and cell["to"] == "A")]
    with _client() as client:
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "infeasible"
        assert body["infeasibleReasons"].get("NO_ROUTE", 0) >= 1
        assert body["suggestions"]


def test_plan_api_least_walk_uses_matrix_distance():
    payload = _base_request()
    payload["preference"] = "least_walk"
    payload["tasks"] = [{
        "id": "T",
        "options": [
            {"placeId": "A", "serviceSeconds": 0, "serviceSourceKind": "user-input"},
            {"placeId": "B", "serviceSeconds": 0, "serviceSourceKind": "user-input"},
        ],
    }]
    payload["travelTimes"] = [
        {"from": "S", "to": "A", "durationSeconds": 100, "distanceM": 50, "sourceKind": "api-cache"},
        {"from": "A", "to": "H", "durationSeconds": 100, "distanceM": 50, "sourceKind": "api-cache"},
        {"from": "S", "to": "B", "durationSeconds": 50, "distanceM": 500, "sourceKind": "api-cache"},
        {"from": "B", "to": "H", "durationSeconds": 50, "distanceM": 500, "sourceKind": "api-cache"},
    ]
    with _client() as client:
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 200
        best = resp.json()["alternatives"][0]
        assert best["stops"][0]["placeId"] == "A"
        assert best["totalWalkingM"] == 100


def test_plan_api_rejects_non_baidu_od_source():
    payload = _base_request()
    for cell in payload["travelTimes"]:
        cell["sourceKind"] = "synthetic-assumption"
    with _client() as client:
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_od_ready_5x3_api_cache_bench_passes_p95_gate():
    import math
    import statistics
    import sys
    import time
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.demo.benchmark_plans_api import build_request, nearest_rank

    from api.app.services.planning_service import PlanningService
    from api.app.models.api import PlanRequest

    service = PlanningService()
    payload = PlanRequest(**build_request())
    assert payload.travel_times
    assert all(cell.source_kind == "api-cache" for cell in payload.travel_times)

    durations = []
    result = None
    for _ in range(30):
        started = time.perf_counter()
        result = service.plan(payload)
        durations.append((time.perf_counter() - started) * 1000.0)
    durations.sort()
    assert result["status"] == "ready"
    assert len(result["alternatives"]) > 0
    assert durations[math.ceil(0.95 * len(durations)) - 1] < 1000
    assert statistics.median(durations) < 1000
    assert nearest_rank(durations, 0.95) < 1000


def test_plan_api_error_cells_report_od_unavailable_not_no_route():
    # T212：status=error（缺测/上游失败）不得与百度明确无路（no_route）合并为 NO_ROUTE。
    payload = _base_request()
    for cell in payload["travelTimes"]:
        if cell["from"] == "S" and cell["to"] == "A":
            cell["status"] = "error"
            cell["durationSeconds"] = None
            cell["distanceM"] = None
    with _client() as client:
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "infeasible"
        assert body["infeasibleReasons"].get("OD_UNAVAILABLE", 0) >= 1
        assert body["infeasibleReasons"].get("NO_ROUTE", 0) == 0
        assert any("缺百度测时" in s for s in body["suggestions"])


def test_plan_api_no_route_cells_keep_no_route():
    # 回归：百度明确无路仍报 NO_ROUTE，不被 OD_UNAVAILABLE 吞掉。
    payload = _base_request()
    for cell in payload["travelTimes"]:
        if cell["from"] == "S" and cell["to"] == "A":
            cell["status"] = "no_route"
            cell["durationSeconds"] = None
            cell["distanceM"] = None
    with _client() as client:
        resp = client.post("/api/plans", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "infeasible"
        assert body["infeasibleReasons"].get("NO_ROUTE", 0) >= 1
        assert body["infeasibleReasons"].get("OD_UNAVAILABLE", 0) == 0


def test_plan_api_ready_result_carries_unknown_hours_warnings():
    # T212：未知营业时间不阻塞规划，但 ready 结果必须带 UNKNOWN_HOURS 警告。
    with _client() as client:
        resp = client.post("/api/plans", json=_base_request())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert any(str(w).startswith("UNKNOWN_HOURS") for w in body["warnings"])
