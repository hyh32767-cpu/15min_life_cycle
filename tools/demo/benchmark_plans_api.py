# -*- coding: utf-8 -*-
"""OD-ready 规划 API 基准:5 任务 x 3 候选，合成 api-cache OD 30 次。

用法:
    python3 tools/demo/benchmark_plans_api.py [--runs 30] [--json-out PATH]

calibre: 合成 OD（全部 sourceKind=api-cache，经 PlanningService.plan
纯内存规划；零 live 百度调用，不触网）。合成-OD 口径见
tools/demo/benchmark_planner.py。
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

from api.app.models.api import PlanRequest  # noqa: E402
from api.app.services.planning_service import PlanningService  # noqa: E402


def deterministic_travel_seconds(a: str, b: str) -> int:
    digest = hashlib.md5(f"{a}>{b}".encode("utf-8")).hexdigest()
    return 60 + (int(digest, 16) % 240)


def nearest_rank(sorted_values: list, fraction: float) -> float:
    if not sorted_values:
        raise ValueError("empty samples")
    index = math.ceil(fraction * len(sorted_values)) - 1
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def build_request() -> dict:
    """17 节点形状：S,H + 5 任务 x 3 候选，仅 planner 实际查询的有向 legs。"""
    candidates = [f"P{t}_{i}" for t in range(5) for i in range(3)]
    legs: list[dict] = []
    for cand in candidates:
        secs = deterministic_travel_seconds("S", cand)
        legs.append({"from": "S", "to": cand, "durationSeconds": secs,
                     "distanceM": secs * 2, "sourceKind": "api-cache"})
        secs = deterministic_travel_seconds(cand, "H")
        legs.append({"from": cand, "to": "H", "durationSeconds": secs,
                     "distanceM": secs * 2, "sourceKind": "api-cache"})
    for t1 in range(5):
        for t2 in range(5):
            if t1 == t2:
                continue
            for i in range(3):
                for j in range(3):
                    a, b = f"P{t1}_{i}", f"P{t2}_{j}"
                    secs = deterministic_travel_seconds(a, b)
                    legs.append({"from": a, "to": b, "durationSeconds": secs,
                                 "distanceM": secs * 2, "sourceKind": "api-cache"})
    tasks = [
        {"id": f"T{t}",
         "options": [{"placeId": f"P{t}_{i}", "serviceSeconds": 120,
                      "serviceSourceKind": "user-input"} for i in range(3)]}
        for t in range(5)
    ]
    return {
        "startId": "S",
        "endId": "H",
        "departureSeconds": 9 * 3600,
        "deadlineSeconds": 20 * 3600,
        "tasks": tasks,
        "travelTimes": legs,
        "preference": "fastest",
        "maxAlternatives": 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="OD-ready 规划 API 基准（api-cache 回放）")
    parser.add_argument("--runs", type=int, default=30, help="重复次数（默认 30）")
    parser.add_argument("--json-out", type=str, default=None, help="可选：结果 JSON 写出路径")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs 必须 >= 1")

    service = PlanningService()
    payload = PlanRequest(**build_request())
    durations: list[float] = []
    result: dict | None = None
    for _ in range(args.runs):
        t0 = time.perf_counter()
        result = service.plan(payload)
        durations.append((time.perf_counter() - t0) * 1000.0)

    durations.sort()
    p50 = statistics.median(durations)
    p95 = nearest_rank(durations, 0.95)
    out = {
        "runs": len(durations),
        "tasks": 5,
        "candidatesPerTask": 3,
        "legs": len(payload.travel_times),
        "status": result["status"] if result else None,
        "alternatives": len(result["alternatives"]) if result else 0,
        "p50Ms": round(p50, 2),
        "p95Ms": round(p95, 2),
        "maxMs": round(max(durations), 2),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    assert out["p95Ms"] < 1000, f"P95 gate 失败: {out['p95Ms']}ms >= 1000ms"


if __name__ == "__main__":
    main()
