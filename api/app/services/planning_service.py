# -*- coding: utf-8 -*-
"""结构化 OD + 任务 -> 方案。纯规划服务,不访问百度。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from core.planner import PlaceNode, TaskOption, TaskSpec, plan_tasks
from core.timewindow import OpeningWindow

from ..models.api import PlanRequest
from .errors import ServiceError


class PlanningService:
    def plan(self, request: PlanRequest) -> dict:
        task_ids = [task.id for task in request.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ServiceError("VALIDATION_ERROR", "任务 id 不能重复")
        known_tasks = set(task_ids)
        for task in request.tasks:
            for predecessor in task.precedence_ids:
                if predecessor not in known_tasks:
                    raise ServiceError("VALIDATION_ERROR",
                                       f"前置任务不存在: {predecessor}")
        if request.preference not in {"fastest", "least_walk"}:
            raise ServiceError("VALIDATION_ERROR", "preference 只能是 fastest 或 least_walk")

        travel: Dict[Tuple[str, str], Optional[float]] = {}
        source_kind: Dict[Tuple[str, str], str] = {}
        distance: Dict[Tuple[str, str], Optional[float]] = {}
        leg_error: Dict[Tuple[str, str], bool] = {}
        for cell in request.travel_times:
            if cell.status == "ok" and cell.source_kind not in {"live-api", "api-cache"}:
                raise ServiceError(
                    "VALIDATION_ERROR",
                    f"可用 OD 必须引用百度 live-api/api-cache: {cell.from_id}->{cell.to_id}",
                )
            key = (cell.from_id, cell.to_id)
            if cell.status == "ok" and cell.duration_seconds is not None:
                travel[key] = float(cell.duration_seconds)
            else:
                travel[key] = None
            # T212：status=error（缺测/上游失败）与 no_route（百度明确无路）区分记录；
            # 规划层都判不可行，但原因码不同，不静默合并。
            leg_error[key] = cell.status == "error"
            source_kind[key] = cell.source_kind
            distance[key] = float(cell.distance_m) if cell.distance_m is not None else None

        tasks = []
        for task in request.tasks:
            options = []
            for option in task.options:
                windows = tuple(
                    OpeningWindow(item.opens_seconds, item.closes_seconds)
                    for item in (option.windows or []))
                window = None
                if option.window is not None:
                    window = OpeningWindow(option.window.opens_seconds,
                                           option.window.closes_seconds)
                options.append(TaskOption(
                    task_id=task.id,
                    place=PlaceNode(option.place_id, option.place_id),
                    service_seconds=option.service_seconds,
                    window=window,
                    windows=windows,
                    service_source_kind=option.service_source_kind,
                    window_source_kind=option.window_source_kind,
                ))
            tasks.append(TaskSpec(
                id=task.id,
                options=tuple(options),
                required=task.required,
                precedence=tuple(task.precedence_ids),
            ))

        result = plan_tasks(
            start_id=request.start_id,
            end_id=request.end_id,
            departure_seconds=request.departure_seconds,
            deadline_seconds=request.deadline_seconds,
            tasks=tasks,
            travel_time=lambda a, b: travel.get((a, b)),
            travel_source_kind=lambda a, b: source_kind.get((a, b)),
            walking_distance=(lambda a, b: distance.get((a, b)))
            if request.preference == "least_walk" else None,
            preference=request.preference,
            max_alternatives=request.max_alternatives,
        )
        out = result.as_dict()
        if out["status"] == "infeasible" and any(leg_error.values()):
            count = int(out.get("infeasibleReasons", {}).pop("NO_ROUTE", 0))
            if count:
                out["infeasibleReasons"]["OD_UNAVAILABLE"] = (
                    out["infeasibleReasons"].get("OD_UNAVAILABLE", 0) + count
                )
                out["suggestions"] = [
                    s for s in out["suggestions"]
                    if "更换候选 POI" not in s
                ]
                from core.planner import relaxation_suggestions as _relax
                for s in _relax({"OD_UNAVAILABLE": count}):
                    if s not in out["suggestions"]:
                        out["suggestions"].append(s)
        return out
