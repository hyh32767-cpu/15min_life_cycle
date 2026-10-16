# -*- coding: utf-8 -*-
"""执行中重排:锁定已完成任务,把模拟事件作用在情景层后真实重算。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from fastapi import APIRouter

from core.planner import PlaceNode, TaskOption, TaskSpec
from core.replan import SimulationEvent, replan_tasks
from core.timewindow import OpeningWindow

from ..models.api import ReplanRequest
from ..services.errors import ServiceError

router = APIRouter(tags=["replan"])

_ALLOWED_SOURCES = {"live-api", "api-cache"}
_ALLOWED_EVENTS = {"close_place", "route_delay"}


@router.post("/api/replan")
def create_replan(request: ReplanRequest) -> dict:
    task_ids = [task.id for task in request.tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ServiceError("VALIDATION_ERROR", "任务 id 不能重复")
    known_tasks = set(task_ids)
    if not set(request.completed_task_ids) <= known_tasks:
        raise ServiceError("VALIDATION_ERROR", "已完成任务必须属于本次任务列表")
    for task in request.tasks:
        for predecessor in task.precedence_ids:
            if predecessor not in known_tasks:
                raise ServiceError("VALIDATION_ERROR",
                                   f"前置任务不存在: {predecessor}")
    if request.preference not in {"fastest", "least_walk"}:
        raise ServiceError("VALIDATION_ERROR", "preference 只能是 fastest 或 least_walk")

    travel: Dict[Tuple[str, str], Optional[float]] = {}
    source_kind: Dict[Tuple[str, str], str] = {}
    leg_error: Dict[Tuple[str, str], bool] = {}
    distance: Dict[Tuple[str, str], Optional[float]] = {}
    for cell in request.travel_times:
        if cell.status == "ok" and cell.source_kind not in _ALLOWED_SOURCES:
            raise ServiceError(
                "VALIDATION_ERROR",
                f"可用 OD 必须引用百度 live-api/api-cache: {cell.from_id}->{cell.to_id}",
            )
        key = (cell.from_id, cell.to_id)
        if cell.status == "ok" and cell.duration_seconds is not None:
            travel[key] = float(cell.duration_seconds)
        else:
            travel[key] = None
        # T212：与 plans 路由同语义，error 与 no_route 区分记录。
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

    events = []
    for event in request.events:
        if event.type not in _ALLOWED_EVENTS:
            raise ServiceError("VALIDATION_ERROR",
                               f"未知模拟事件类型: {event.type}")
        events.append(SimulationEvent(
            id=event.id,
            type=event.type,
            target_id=event.target_id,
            delay_seconds=float(event.delay_seconds),
        ))

    result = replan_tasks(
        tasks=tasks,
        completed_task_ids=list(request.completed_task_ids),
        current_node_id=request.current_node_id,
        current_time_seconds=float(request.current_time_seconds),
        deadline_seconds=float(request.deadline_seconds),
        travel_time=lambda a, b: travel.get((a, b)),
        end_id=request.end_id,
        travel_source_kind=lambda a, b: source_kind.get((a, b)),
        walking_distance=lambda a, b: distance.get((a, b)),
        events=events,
        preference=request.preference,
    )
    out = result.as_dict()
    if out["status"] == "infeasible" and any(leg_error.values()):
        from core.planner import relaxation_suggestions as _relax
        count = int(out.get("plan", {}).get("infeasibleReasons", {}).pop("NO_ROUTE", 0))
        if count:
            plan = out["plan"]
            plan["infeasibleReasons"]["OD_UNAVAILABLE"] = (
                plan["infeasibleReasons"].get("OD_UNAVAILABLE", 0) + count
            )
            plan["suggestions"] = [
                s for s in plan["suggestions"]
                if "更换候选 POI" not in s
            ]
            for s in _relax({"OD_UNAVAILABLE": count}):
                if s not in plan["suggestions"]:
                    plan["suggestions"].append(s)
    return out
