"""独立小图穷举 oracle：不调用内核的排序/时间窗实现。"""
import itertools
import random

import pytest

from core.planner import PlaceNode, TaskOption, TaskSpec, plan_tasks
from core.timewindow import OpeningWindow


@pytest.mark.parametrize("preference", ["fastest", "least_walk"])
def test_random_directed_graphs_against_independent_oracle(preference):
    rng = random.Random(20261007)
    for _ in range(60):
        tasks = [TaskSpec(str(i), tuple(
            TaskOption(str(i), PlaceNode(f"{i}-{j}"), rng.randrange(0, 50),
                       window=OpeningWindow(0, rng.randrange(150, 500)))
            for j in range(2))) for i in range(3)]
        nodes = ["S", "H", *[o.place.id for t in tasks for o in t.options]]
        times = {(a, b): rng.randrange(5, 100) for a in nodes for b in nodes if a != b and rng.random() > .1}
        distances = {key: rng.randrange(1, 200) for key in times}
        deadline = rng.randrange(180, 550)
        candidates = []
        for assignment in itertools.product(*(t.options for t in tasks)):
            for order in itertools.permutations(assignment):
                now, travel, walk, at = 0, 0, 0, "S"
                for option in order:
                    edge = (at, option.place.id)
                    if edge not in times:
                        break
                    now += times[edge]
                    now = max(now, option.window.opens_seconds) + option.service_seconds
                    if now > option.window.closes_seconds:
                        break
                    travel += times[edge]
                    walk += distances[edge]
                    at = option.place.id
                else:
                    if (at, "H") not in times:
                        continue
                    now += times[at, "H"]
                    travel += times[at, "H"]
                    walk += distances[at, "H"]
                    if now <= deadline:
                        seq = tuple(f"{o.task_id}:{o.place.id}" for o in order)
                        candidates.append((walk, now, travel, seq) if preference == "least_walk" else (now, travel, seq))
        result = plan_tasks(start_id="S", end_id="H", departure_seconds=0,
                            deadline_seconds=deadline, tasks=tasks,
                            travel_time=lambda a, b: times.get((a, b)),
                            walking_distance=lambda a, b: distances.get((a, b)),
                            preference=preference)
        assert (result.status == "ready") == bool(candidates)
        if candidates:
            assert result.alternatives[0].sequence == min(candidates)[-1]
