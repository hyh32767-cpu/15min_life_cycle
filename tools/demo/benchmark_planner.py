# -*- coding: utf-8 -*-
"""规划器性能基准:OD 齐备后 5 任务 x 3 候选重复 N 次。

用法:
    python3 tools/demo/benchmark_planner.py [--runs 30] [--json-out PATH]

calibre: synthetic-travel（OD 为 hashlib md5 确定性派生，非百度数据，
同一进程/跨进程可复现）；OD-ready api-cache 回放口径见
tools/demo/benchmark_plans_api.py。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.planner import PlaceNode, TaskOption, TaskSpec, plan_tasks  # noqa: E402


def deterministic_travel_seconds(a: str, b: str) -> int:
    """跨进程稳定的确定性 OD（替代 per-process 随机的 hash()）。"""
    digest = hashlib.md5(f"{a}>{b}".encode("utf-8")).hexdigest()
    return 60 + (int(digest, 16) % 240)


def nearest_rank(sorted_values: list, fraction: float) -> float:
    """nearest-rank 分位数：sorted_values[ceil(frac*n)-1]。"""
    if not sorted_values:
        raise ValueError("empty samples")
    index = math.ceil(fraction * len(sorted_values)) - 1
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def main() -> None:
    parser = argparse.ArgumentParser(description="规划器性能基准（确定性合成 OD）")
    parser.add_argument("--runs", type=int, default=30, help="重复次数（默认 30）")
    parser.add_argument("--json-out", type=str, default=None, help="可选：结果 JSON 写出路径")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs 必须 >= 1")

    tasks = []
    nodes = ["S", "H"] + [f"P{t}_{i}" for t in range(5) for i in range(3)]
    travel = {}
    for a in nodes:
        for b in nodes:
            if a != b:
                travel[(a, b)] = deterministic_travel_seconds(a, b)
    for index in range(5):
        options = tuple(
            TaskOption(task_id=f"T{index}", place=PlaceNode(f"P{index}_{i}", f"P{index}_{i}"),
                       service_seconds=120)
            for i in range(3)
        )
        tasks.append(TaskSpec(id=f"T{index}", options=options))

    durations = []
    results = None
    for _ in range(args.runs):
        t0 = time.perf_counter()
        results = plan_tasks(
            start_id="S", end_id="H", departure_seconds=9 * 3600,
            deadline_seconds=20 * 3600, tasks=tasks,
            travel_time=lambda a, b: travel.get((a, b)),
            max_alternatives=3,
        )
        durations.append((time.perf_counter() - t0) * 1000.0)

    durations.sort()
    p50 = statistics.median(durations)
    p95 = nearest_rank(durations, 0.95)
    payload = {
        "runs": len(durations),
        "tasks": len(tasks),
        "candidatesPerTask": 3,
        "status": results.status if results else None,
        "alternatives": len(results.alternatives) if results else 0,
        "p50Ms": round(p50, 2),
        "p95Ms": round(p95, 2),
        "maxMs": round(max(durations), 2),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
