# -*- coding: utf-8 -*-
import pytest
from pydantic import ValidationError

from api.app.models.common import Coord, SourceKind
from api.app.models.domain import (Assumption, CommuteRequest, PlaceRef, RouteLeg,
                                   ScenarioEvent, TaskSpec, TravelMatrixCell)


def _place(uid: str, name: str = "地点") -> PlaceRef:
    return PlaceRef(uid=uid, name=name, coord=Coord(lng=116.3, lat=39.9),
                    source="live-api")


def test_place_ref_requires_coord_and_source():
    valid = PlaceRef(
        uid="u1",
        name="测试药店",
        coord=Coord(lng=116.3, lat=39.9),
        source="live-api",
    )
    assert valid.source == SourceKind.LIVE_API
    with pytest.raises(ValidationError):
        PlaceRef(name="无坐标", source="live-api")
    with pytest.raises(ValidationError):
        PlaceRef(name="无来源", coord=Coord(lng=116.3, lat=39.9))


def test_assumption_rejects_non_synthetic_source_and_missing_source():
    with pytest.raises(ValidationError):
        Assumption(targetId="p1", field="waitSeconds", value=120, seed=1,
                   reason="排队", sourceKind="user-input")
    with pytest.raises(ValidationError):
        Assumption(targetId="p1", field="waitSeconds", value=120, seed=1, reason="排队")


def test_task_rejects_negative_service_and_wrong_kind_fields():
    base = {"id": "t1", "kind": "fixed", "fixedPlaceId": "p1"}
    assert TaskSpec(serviceSeconds=0, **base).service_seconds == 0
    with pytest.raises(ValidationError):
        TaskSpec(serviceSeconds=-1, **base)
    with pytest.raises(ValidationError):
        TaskSpec(id="t2", kind="fixed", category="药店")
    with pytest.raises(ValidationError):
        TaskSpec(id="t3", kind="category", category="药店", precedenceIds=["t3"])


def test_travel_matrix_cell_and_event_require_source():
    with pytest.raises(ValidationError):
        TravelMatrixCell(**{"from": "a", "to": "b", "durationSeconds": 10, "distanceM": 20})
    cell = TravelMatrixCell(**{
        "from": "a", "to": "b", "durationSeconds": 10, "distanceM": 20,
        "status": "ok", "sourceKind": "api-cache",
    })
    assert cell.source_kind == SourceKind.API_CACHE

    with pytest.raises(ValidationError):
        ScenarioEvent(id="e1", scenarioTimeSeconds=100, type="close", targetId="p1")
    event = ScenarioEvent(
        id="e1", scenarioTimeSeconds=100, type="close", targetId="p1",
        sourceKind="synthetic-assumption",
    )
    assert event.scenario_time_seconds == 100


def test_commute_request_rejects_negative_budget_and_bad_deadline():
    payload = {
        "start": _place("s"),
        "end": _place("h"),
        "departureAt": "2026-09-21T18:00:00+08:00",
        "deadlineAt": "2026-09-21T19:00:00+08:00",
        "category": "药店",
        "isochroneSeconds": 900,
        "maxExtraTravelSeconds": 600,
        "serviceSeconds": 300,
        "routePolicy": "free",
    }
    assert CommuteRequest(**payload).max_extra_travel_seconds == 600
    with pytest.raises(ValidationError):
        CommuteRequest(**{**payload, "maxExtraTravelSeconds": -1})
    with pytest.raises(ValidationError):
        CommuteRequest(**{**payload, "deadlineAt": "2026-09-21T17:00:00+08:00"})


def test_route_leg_requires_non_negative_and_source():
    with pytest.raises(ValidationError):
        RouteLeg(**{"from": "a", "to": "b", "travelSeconds": -1, "walkingM": 0,
                    "sourceKind": "live-api"})
    leg = RouteLeg(**{"from": "a", "to": "b", "travelSeconds": 10, "walkingM": 20,
                      "sourceKind": "live-api"})
    assert leg.travel_seconds == 10
