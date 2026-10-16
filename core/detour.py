# -*- coding: utf-8 -*-
"""沿途绕行成本:自由重规划与保留基准路线模式。

公式对应 docs/19 §7。所有时间为秒;缺失路段的组合不参与最优解。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class DetourResult:
    feasible: bool
    total_travel_seconds: Optional[float]
    extra_travel_seconds: Optional[float]
    finish_seconds: Optional[float]
    reason: str = ""


@dataclass(frozen=True)
class KeepRouteCandidate:
    entry_index: int
    return_index: int
    total_travel_seconds: float
    extra_travel_seconds: float
    finish_seconds: float


@dataclass(frozen=True)
class KeepRouteResult:
    feasible: bool
    best: Optional[KeepRouteCandidate]
    candidates: List[KeepRouteCandidate]
    reason: str = ""


def free_detour(t_start_to_poi: Optional[float], t_poi_to_end: Optional[float],
                baseline_seconds: float, *, wait_seconds: float = 0.0,
                service_seconds: float = 0.0, departure_seconds: float = 0.0,
                max_extra_travel_seconds: Optional[float] = None,
                deadline_seconds: Optional[float] = None) -> DetourResult:
    if t_start_to_poi is None or t_poi_to_end is None:
        return DetourResult(False, None, None, None, "NO_ROUTE")
    total_travel = float(t_start_to_poi) + float(t_poi_to_end)
    extra = total_travel - float(baseline_seconds)
    finish = float(departure_seconds) + total_travel + float(wait_seconds) + float(service_seconds)
    if max_extra_travel_seconds is not None and extra > max_extra_travel_seconds:
        return DetourResult(False, total_travel, extra, finish, "EXTRA_BUDGET")
    if deadline_seconds is not None and finish > deadline_seconds:
        return DetourResult(False, total_travel, extra, finish, "DEADLINE")
    return DetourResult(True, total_travel, extra, finish, "")


def keep_route_detour(prefix_seconds: List[Optional[float]],
                      route_to_poi: List[Optional[float]],
                      poi_to_route: List[Optional[float]],
                      baseline_seconds: float, *,
                      wait_seconds: float = 0.0,
                      service_seconds: float = 0.0,
                      departure_seconds: float = 0.0,
                      max_extra_travel_seconds: Optional[float] = None,
                      deadline_seconds: Optional[float] = None) -> KeepRouteResult:
    """枚举有序接入/返回节点 i <= j,不生成逆序折返。"""
    n = len(prefix_seconds)
    if n == 0 or n != len(route_to_poi) or n != len(poi_to_route):
        raise ValueError("prefix/route_to_poi/poi_to_route 长度必须一致且非空")
    candidates: List[KeepRouteCandidate] = []
    for i in range(n):
        if prefix_seconds[i] is None or route_to_poi[i] is None:
            continue
        for j in range(i, n):
            if poi_to_route[j] is None or prefix_seconds[j] is None:
                continue
            total_travel = (
                float(prefix_seconds[i])
                + float(route_to_poi[i])
                + float(poi_to_route[j])
                + (float(baseline_seconds) - float(prefix_seconds[j]))
            )
            extra = total_travel - float(baseline_seconds)
            finish = float(departure_seconds) + total_travel + float(wait_seconds) + float(service_seconds)
            if max_extra_travel_seconds is not None and extra > max_extra_travel_seconds:
                continue
            if deadline_seconds is not None and finish > deadline_seconds:
                continue
            candidates.append(KeepRouteCandidate(i, j, total_travel, extra, finish))
    if not candidates:
        return KeepRouteResult(False, None, [], "NO_FEASIBLE_IJ")
    candidates.sort(key=lambda item: (item.finish_seconds, item.extra_travel_seconds))
    return KeepRouteResult(True, candidates[0], candidates, "")
