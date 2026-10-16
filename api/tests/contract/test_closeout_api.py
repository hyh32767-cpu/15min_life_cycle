# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from api.app.main import app


def _client() -> TestClient:
    return TestClient(app)


def _replan_request() -> dict:
    return {
        "tasks": [
            {"id": "A", "options": [{"placeId": "A", "serviceSeconds": 60,
                                     "serviceSourceKind": "user-input"}]},
            {"id": "B", "options": [{"placeId": "B1", "serviceSeconds": 60,
                                     "serviceSourceKind": "user-input"},
                                    {"placeId": "B2", "serviceSeconds": 60,
                                     "serviceSourceKind": "user-input"}]},
        ],
        "completedTaskIds": ["A"],
        "currentNodeId": "A",
        "endId": "H",
        "currentTimeSeconds": 100,
        "deadlineSeconds": 2000,
        "travelTimes": [
            {"from": "A", "to": "B1", "durationSeconds": 100, "sourceKind": "api-cache"},
            {"from": "A", "to": "B2", "durationSeconds": 120, "sourceKind": "api-cache"},
            {"from": "B1", "to": "H", "durationSeconds": 100, "sourceKind": "api-cache"},
            {"from": "B2", "to": "H", "durationSeconds": 100, "sourceKind": "api-cache"},
        ],
        "events": [{"id": "e1", "type": "close_place", "targetId": "B1"}],
        "preference": "fastest",
    }


def test_replan_locks_completed_and_filters_closed_option():
    with _client() as client:
        resp = client.post("/api/replan", json=_replan_request())
        assert resp.status_code == 200
        body = resp.json()
        assert body["lockedCompleted"] == ["A"]
        assert body["appliedEvents"] == ["e1"]
        places = {stop["placeId"] for alt in body["plan"]["alternatives"]
                  for stop in alt["stops"]}
        assert "A" not in places
        assert "B1" not in places
        assert "B2" in places


def test_replan_rejects_non_baidu_od_source():
    payload = _replan_request()
    for cell in payload["travelTimes"]:
        cell["sourceKind"] = "synthetic-assumption"
    with _client() as client:
        resp = client.post("/api/replan", json=payload)
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_explore_over_budget_is_infeasible():
    payload = {
        "budgetSeconds": 500,
        "serviceSeconds": 300,
        "waitSeconds": 0,
        "candidates": [{"placeId": "P1"}, {"placeId": "P2"}],
        "legs": [
            {"candidateId": "P1", "durationSecondsStart": 100,
             "durationSecondsReturn": 100, "statusStart": "ok",
             "statusReturn": "ok", "sourceKind": "api-cache"},
            {"candidateId": "P2", "durationSecondsStart": None,
             "durationSecondsReturn": 100, "statusStart": "error",
             "statusReturn": "ok", "sourceKind": "api-cache"},
        ],
    }
    with _client() as client:
        resp = client.post("/api/explore/check", json=payload)
        assert resp.status_code == 200
        results = {item["placeId"]: item for item in resp.json()["results"]}
        assert results["P1"] == {"placeId": "P1", "feasible": True,
                                 "totalSeconds": 500.0, "reason": ""}
        assert results["P2"]["feasible"] is False
        assert results["P2"]["reason"] == "NO_ROUTE"
        assert results["P2"]["totalSeconds"] is None


def test_explore_strictly_over_budget_is_infeasible():
    payload = {
        "budgetSeconds": 499,
        "serviceSeconds": 300,
        "waitSeconds": 0,
        "candidates": [{"placeId": "P1"}],
        "legs": [
            {"candidateId": "P1", "durationSecondsStart": 100,
             "durationSecondsReturn": 100, "statusStart": "ok",
             "statusReturn": "ok", "sourceKind": "api-cache"},
        ],
    }
    with _client() as client:
        resp = client.post("/api/explore/check", json=payload)
        assert resp.status_code == 200
        item = resp.json()["results"][0]
        assert item["feasible"] is False
        assert item["totalSeconds"] == 500.0


def test_coverage_unreachable_counts_as_blind_and_delta():
    payload = {
        "thresholdSeconds": 900,
        "gridIds": ["g1", "g2", "g3"],
        "facilityIds": ["f1"],
        "times": [
            {"fromGrid": "g1", "toFacility": "f1",
             "durationSeconds": 100, "status": "ok"},
            {"fromGrid": "g2", "toFacility": "f1",
             "durationSeconds": None, "status": "no_route"},
            {"fromGrid": "g3", "toFacility": "f1",
             "durationSeconds": 5000, "status": "ok"},
        ],
        "newFacilityId": "f2",
        "newFacilityTimes": [
            {"fromGrid": "g2", "toFacility": "f2",
             "durationSeconds": None, "status": "no_route"},
            {"fromGrid": "g3", "toFacility": "f2",
             "durationSeconds": 200, "status": "ok"},
        ],
    }
    with _client() as client:
        resp = client.post("/api/community/coverage", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["coverage"] == {"g1": True, "g2": False, "g3": False}
        assert body["coveredCount"] == 1
        assert body["totalGrids"] == 3
        assert set(body["blindGrids"]) == {"g2", "g3"}
        assert body["delta"] == {"before": 1, "after": 2}


def test_coverage_unknown_pairs_are_not_blind_but_positive_proof_can_short_circuit():
    payload = {"thresholdSeconds": 900, "gridIds": ["g"], "facilityIds": ["f1", "f2"],
               "times": [{"fromGrid": "g", "toFacility": "f1", "status": "error"}]}
    with _client() as client:
        assert client.post("/api/community/coverage", json=payload).status_code == 422
        payload["times"].append({"fromGrid": "g", "toFacility": "f2", "status": "ok", "durationSeconds": 500})
        response = client.post("/api/community/coverage", json=payload)
        assert response.status_code == 200
        assert response.json()["coverage"] == {"g": True}


def test_cases_list_nonempty_and_detail_roundtrip(hermetic_app):
    # F68：经 hermetic_app（FakeAdapter + 临时 DB），无 AK/无网络可过。
    client, _service = hermetic_app
    with client:
        listing = client.get("/api/cases")
        assert listing.status_code == 200
        cases = listing.json()["cases"]
        assert cases, "案例列表为空"
        first = cases[0]
        assert {"id", "title", "region", "summary", "center", "files"} <= set(first)
        detail = client.get(f"/api/cases/{first['id']}")
        assert detail.status_code == 200
        assert detail.json()["caseId"] == first["id"]


def test_cases_missing_id_is_404_api_error(hermetic_app):
    # F68：经 hermetic_app（FakeAdapter + 临时 DB），无 AK/无网络可过。
    client, _service = hermetic_app
    with client:
        resp = client.get("/api/cases/no-such-case")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_ledger_summary_separates_live_and_cache(hermetic_app):
    # F68：经 hermetic_app（FakeAdapter + 临时 DB），无 AK/无网络可过。
    client, _service = hermetic_app
    with client:
        resp = client.get("/api/ledger/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert body["requests"] == body["liveRequests"] + body["cacheHits"]
        assert "liveRequests" in body and "cacheHits" in body


def test_ledger_summary_group_by_stage_is_additive(hermetic_app):
    # F68：经 hermetic_app（FakeAdapter + 临时 DB），无 AK/无网络可过。
    # 空账本时无分组行；写入一条 live 行后分组行可加和。
    client, service = hermetic_app
    with client:
        resp = client.get("/api/ledger/summary", params={"group_by": "stage"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["requests"] == body["liveRequests"] + body["cacheHits"]
        assert body["rows"] == 0
        service.ledger.record(
            trace_id="t1", stage="A1", interface="place_search",
            request_hash="h1", cache_hit=False, status=0,
            requests=1, pairs=1, message="ok", response_hash="r1")
        grouped = client.get("/api/ledger/summary", params={"group_by": "stage"})
        assert grouped.status_code == 200
        grouped_body = grouped.json()
        assert "byStage" in grouped_body
        assert sum(row["rows"] for row in grouped_body["byStage"]) == grouped_body["rows"]
