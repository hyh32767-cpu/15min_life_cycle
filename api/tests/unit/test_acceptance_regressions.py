"""本次算法审查发现的边界回归，全部使用合成 OD，不调用外网。"""
import math

import pytest

from core.isochrone import bisect_ray, compute_isochrone, compute_isochrone_batched
from core.planner import PlaceNode, TaskOption, TaskSpec
from core.replan import replan_tasks


def task(task_id, place_id, precedence=()):
    return TaskSpec(task_id, (TaskOption(task_id, PlaceNode(place_id)),),
                    precedence=precedence)


def test_completed_predecessor_is_satisfied_when_replanning():
    tasks = [task("A", "P"), task("B", "Q", ("A",))]
    result = replan_tasks(tasks=tasks, completed_task_ids=["A"], current_node_id="P",
                          current_time_seconds=100, deadline_seconds=300,
                          travel_time=lambda a, b: {("P", "Q"): 50, ("Q", "H"): 50}.get((a, b)))
    assert result.status == "ready"
    assert result.plan.alternatives[0].finish_seconds == 200
    assert result.plan.alternatives[0].sequence == ("B:Q",)
    assert tasks[1].precedence == ("A",)  # 输入没有被改写


def test_least_walk_replan_uses_distance_and_includes_return():
    tasks = [TaskSpec("T", (TaskOption("T", PlaceNode("A")), TaskOption("T", PlaceNode("B"))))]
    times = {("S", "A"): 100, ("A", "H"): 100, ("S", "B"): 10, ("B", "H"): 10}
    distances = {("S", "A"): 10, ("A", "H"): 10, ("S", "B"): 100, ("B", "H"): 100}
    result = replan_tasks(tasks=tasks, completed_task_ids=[], current_node_id="S",
                          current_time_seconds=0, deadline_seconds=300,
                          travel_time=lambda a, b: times.get((a, b)), preference="least_walk",
                          walking_distance=lambda a, b: distances.get((a, b)))
    assert result.plan.alternatives[0].sequence == ("T:A",)
    assert result.plan.alternatives[0].total_walking_m == 20


def test_budget_can_finish_one_ray_without_claiming_all_directions_complete():
    # 最后一轮只剩一对预算：一条射线完成、另一条未测，不得返回 complete。
    result = compute_isochrone_batched(lambda points: [d for _, d in points],
        threshold_s=900, bearings=[0, 90], tol_m=100, max_pairs=9)
    assert result.radii_m
    assert result.skipped_bearings
    assert result.status == "partial"
    assert result.pairs_used == 9


def test_serial_ray_never_exceeds_probe_budget():
    calls = []
    result = compute_isochrone(lambda b, d: calls.append((b, d)) or d,
                               threshold_s=900, max_probes=3, tol_m=1)
    assert len(calls) == result.pairs_used == 3
    assert not result.radii_m


@pytest.mark.parametrize("value", [math.nan, math.inf, -1])
def test_invalid_measurement_never_creates_radius(value):
    assert not bisect_ray(lambda _: value, threshold_s=900).ok
    result = compute_isochrone_batched(lambda points: [value] * len(points), threshold_s=900)
    assert result.status == "failed"
    assert not result.radii_m


@pytest.mark.parametrize("bearings", [[0, 0], [360], [-1], [math.nan]])
def test_invalid_directions_rejected(bearings):
    with pytest.raises(ValueError):
        compute_isochrone_batched(lambda _: [], threshold_s=900, bearings=bearings)
