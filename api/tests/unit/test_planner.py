# -*- coding: utf-8 -*-
from core.planner import PlaceNode, TaskOption, TaskSpec, plan_tasks
from core.timewindow import OpeningWindow


def _fixed(task_id: str, place_id: str, service: int = 0,
           window: OpeningWindow | None = None, required: bool = True,
           precedence: tuple = ()) -> TaskSpec:
    return TaskSpec(id=task_id, options=(
        TaskOption(task_id=task_id, place=PlaceNode(place_id, place_id),
                   service_seconds=service, window=window),
    ), required=required, precedence=tuple(precedence))


def test_planner_compares_whole_order_not_individual_detours():
    travel = {
        ("S", "A"): 100, ("S", "B"): 160,
        ("A", "B"): 80, ("B", "A"): 80,
        ("A", "H"): 120, ("B", "H"): 100,
    }
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=1000,
        tasks=[_fixed("A", "A", 100), _fixed("B", "B", 100)],
        travel_time=lambda a, b: travel.get((a, b)),
    )
    assert result.status == "ready"
    assert result.alternatives[0].sequence == ("A:A", "B:B")
    assert result.alternatives[0].finish_seconds == 480


def test_planner_waits_for_opening_and_allows_exact_close():
    window = OpeningWindow(200, 300)
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=300,
        tasks=[_fixed("A", "A", 50, window)],
        travel_time=lambda a, b: {"S,A": 100, "A,H": 50}.get(f"{a},{b}"),
    )
    assert result.status == "ready"
    stop = result.alternatives[0].stops[0]
    assert stop.arrival_seconds == 100
    assert stop.start_seconds == 200
    assert stop.wait_seconds == 100
    assert result.alternatives[0].finish_seconds == 300


def test_planner_rejects_service_past_close():
    window = OpeningWindow(200, 300)
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=1000,
        tasks=[_fixed("A", "A", 120, window)],
        travel_time=lambda a, b: {"S,A": 100, "A,H": 50}.get(f"{a},{b}"),
    )
    assert result.status == "infeasible"
    assert result.infeasible_reasons.get("CLOSED", 0) >= 1


def test_planner_honors_precedence_and_detects_cycle():
    travel = {"S,A": 10, "A,B": 10, "B,H": 10}
    a = _fixed("A", "A")
    b = _fixed("B", "B")
    ok_result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=100,
        tasks=[TaskSpec(id="A", options=a.options, precedence=()),
               TaskSpec(id="B", options=b.options, precedence=("A",))],
        travel_time=lambda x, y: travel.get(f"{x},{y}"),
    )
    assert ok_result.status == "ready"
    assert ok_result.alternatives[0].sequence == ("A:A", "B:B")

    cycle = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=100,
        tasks=[TaskSpec(id="A", options=a.options, precedence=("B",)),
               TaskSpec(id="B", options=b.options, precedence=("A",))],
        travel_time=lambda x, y: travel.get(f"{x},{y}"),
    )
    assert cycle.status == "infeasible"
    assert cycle.infeasible_reasons.get("PRECEDENCE_CYCLE") == 1


def test_planner_rejects_missing_route_without_fake_leg():
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=100,
        tasks=[_fixed("A", "A")],
        travel_time=lambda a, b: None,
    )
    assert result.status == "infeasible"
    assert result.infeasible_reasons.get("NO_ROUTE", 0) >= 1


def test_least_walk_objective_keeps_same_sequences_and_dedupes():
    task = TaskSpec(id="T", options=(
        TaskOption(task_id="T", place=PlaceNode("A", "A")),
        TaskOption(task_id="T", place=PlaceNode("B", "B")),
    ))
    travel = {"S,A": 100, "A,H": 100, "S,B": 50, "B,H": 50}
    walk = {"S,A": 100, "A,H": 100, "S,B": 500, "B,H": 500}
    fastest = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=1000,
        tasks=[task], travel_time=lambda a, b: travel.get(f"{a},{b}"),
    )
    least_walk = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=1000,
        tasks=[task], travel_time=lambda a, b: travel.get(f"{a},{b}"),
        preference="least_walk", walking_distance=lambda a, b: walk.get(f"{a},{b}"),
    )
    assert fastest.alternatives[0].sequence == ("T:B",)
    assert least_walk.alternatives[0].sequence == ("T:A",)
    assert len({alt.sequence for alt in least_walk.alternatives}) == len(least_walk.alternatives)


def test_optional_task_skipped_when_over_deadline():
    travel = {("S", "A"): 100, ("A", "H"): 100, ("S", "B"): 500,
              ("B", "H"): 50, ("A", "B"): 800, ("B", "A"): 800}
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=350,
        tasks=[_fixed("A", "A", service=50),
               _fixed("B", "B", service=50, required=False)],
        travel_time=lambda a, b: travel.get((a, b)),
    )
    assert result.status == "ready"
    assert result.alternatives[0].sequence == ("A:A",)


def test_optional_task_included_when_fits():
    travel = {("S", "A"): 100, ("A", "H"): 100, ("S", "B"): 500,
              ("B", "H"): 50, ("A", "B"): 800, ("B", "A"): 800}
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=2000,
        tasks=[_fixed("A", "A", service=50),
               _fixed("B", "B", service=50, required=False)],
        travel_time=lambda a, b: travel.get((a, b)),
    )
    assert result.status == "ready"
    assert result.alternatives[0].sequence == ("A:A", "B:B")


def test_optional_successor_skipped_with_optional_predecessor():
    travel = {("S", "A"): 100, ("A", "H"): 100, ("S", "B"): 500,
              ("B", "H"): 50, ("A", "B"): 800, ("B", "A"): 800}
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=350,
        tasks=[_fixed("R", "R", service=10),
               _fixed("A", "A", service=50, required=False),
               _fixed("B", "B", service=50, required=False, precedence=("A",))],
        travel_time=lambda a, b: travel.get((a, b), 50),
    )
    assert result.status == "ready"
    assert "B:B" not in result.alternatives[0].sequence


def test_multi_window_picks_earliest_feasible_segment():
    from core.timewindow import OpeningWindow
    travel = {("S", "A"): 100, ("A", "H"): 100}
    option = TaskOption(task_id="A", place=PlaceNode("A", "A"), service_seconds=100,
                        windows=(OpeningWindow(0, 150), OpeningWindow(500, 1000)))
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=2000,
        tasks=[TaskSpec(id="A", options=(option,))],
        travel_time=lambda a, b: travel.get((a, b)),
    )
    assert result.status == "ready"
    assert result.alternatives[0].stops[0].start_seconds == 500


def test_unknown_hours_warn_without_blocking():
    # T212：无营业窗口不判 CLOSED，但 warnings 必须区分“未知未限”。
    result = plan_tasks(
        start_id="S", end_id="H", departure_seconds=0, deadline_seconds=1000,
        tasks=[_fixed("A", "A", 50)],
        travel_time=lambda a, b: {("S", "A"): 100, ("A", "H"): 100}.get((a, b)),
    )
    assert result.status == "ready"
    assert any(w.startswith("UNKNOWN_HOURS:A:A") for w in result.warnings)
