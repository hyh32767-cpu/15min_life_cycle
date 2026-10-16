# -*- coding: utf-8 -*-
from core.planner import PlaceNode, TaskOption, TaskSpec
from core.replan import SimulationEvent, replan_tasks


def _fixed(task_id: str, place_id: str, service: int = 0) -> TaskSpec:
    return TaskSpec(id=task_id, options=(
        TaskOption(task_id=task_id, place=PlaceNode(place_id, place_id),
                   service_seconds=service),
    ))


def test_replan_locks_completed_task_and_plans_remaining_from_current_node():
    tasks = [_fixed("A", "A"), _fixed("B", "B", 100)]
    travel = {("A", "B"): 50, ("B", "H"): 50}
    result = replan_tasks(
        tasks=tasks, completed_task_ids=["A"], current_node_id="A",
        current_time_seconds=200, deadline_seconds=1000,
        travel_time=lambda a, b: travel.get((a, b)),
        end_id="H",
    )
    assert result.status == "ready"
    assert result.locked_completed == ["A"]
    assert result.plan.alternatives[0].sequence == ("B:B",)
    assert result.plan.alternatives[0].finish_seconds == 400


def test_simulated_close_place_changes_scenario_options_only():
    closed_b = SimulationEvent(id="e1", type="close_place", target_id="B")
    tasks = [
        _fixed("T", "A"),
        TaskSpec(id="T2", options=(
            TaskOption(task_id="T2", place=PlaceNode("A", "A")),
            TaskOption(task_id="T2", place=PlaceNode("B", "B")),
        )),
    ]
    travel = {("S", "A"): 10, ("A", "A"): 10, ("A", "H"): 10,
              ("S", "B"): 10, ("A", "B"): 10, ("B", "H"): 10}
    result = replan_tasks(
        tasks=tasks, completed_task_ids=[], current_node_id="S",
        current_time_seconds=0, deadline_seconds=1000,
        travel_time=lambda a, b: travel.get((a, b)),
        events=[closed_b], end_id="H",
    )
    assert result.status == "ready"
    places = {stop.place_id for alt in result.plan.alternatives for stop in alt.stops}
    assert "B" not in places
    assert result.applied_events == ["e1"]


def test_route_delay_is_derived_source_and_does_not_overwrite_base_od():
    tasks = [_fixed("A", "A")]
    base = {("S", "A"): 100, ("A", "H"): 100}
    event = SimulationEvent(id="delay", type="route_delay", target_id="S->A",
                            delay_seconds=200)
    result = replan_tasks(
        tasks=tasks, completed_task_ids=[], current_node_id="S",
        current_time_seconds=0, deadline_seconds=1000,
        travel_time=lambda a, b: base.get((a, b)),
        travel_source_kind=lambda _a, _b: "api-cache",
        events=[event], end_id="H",
    )
    best = result.plan.alternatives[0]
    assert best.finish_seconds == 400
    assert best.stops[0].travel_source_kind == "synthetic-assumption"
    assert base[("S", "A")] == 100  # 原始 API OD 未被改写


def test_required_task_closed_is_infeasible_not_silent():
    tasks = [_fixed("A", "A")]
    event = SimulationEvent(id="close", type="close_place", target_id="A")
    result = replan_tasks(
        tasks=tasks, completed_task_ids=[], current_node_id="S",
        current_time_seconds=0, deadline_seconds=1000,
        travel_time=lambda a, b: 100, events=[event], end_id="H",
    )
    assert result.status == "infeasible"
    assert result.reason.startswith("REQUIRED_TASK_CLOSED")
    assert result.plan.infeasible_reasons.get("REQUIRED_TASK_CLOSED", 0) >= 1


def test_optional_task_closed_is_silently_removed():
    optional_b = TaskSpec(id="B", options=_fixed("B", "B").options,
                          required=False, precedence=())
    tasks = [_fixed("A", "A"), optional_b]
    event = SimulationEvent(id="close", type="close_place", target_id="B")
    result = replan_tasks(
        tasks=tasks, completed_task_ids=[], current_node_id="S",
        current_time_seconds=0, deadline_seconds=10000,
        travel_time=lambda a, b: 100, events=[event], end_id="H",
    )
    assert result.status == "ready"
    assert result.plan.alternatives[0].sequence == ("A:A",)
