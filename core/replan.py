# -*- coding: utf-8 -*-
"""执行中重排:锁定已完成任务,把模拟事件作用在情景层。

契约 docs/19 §10:
- 已完成任务不再参与枚举;
- 模拟关店只在候选过滤层生效,不改写百度 POI 原始状态;
- 模拟路线延误只叠加在派生 OD 上,基础 API 响应不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Sequence, Tuple

from core.planner import (Alternative, PlanResult, TaskSpec, TravelFn, TravelSourceFn,
                          plan_tasks, relaxation_suggestions)


@dataclass(frozen=True)
class SimulationEvent:
    id: str
    type: str  # close_place | route_delay
    target_id: str
    delay_seconds: float = 0.0
    source_kind: str = "synthetic-assumption"


@dataclass
class ReplanResult:
    status: str
    plan: PlanResult
    locked_completed: List[str] = field(default_factory=list)
    applied_events: List[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "plan": self.plan.as_dict(),
            "lockedCompleted": self.locked_completed,
            "appliedEvents": self.applied_events,
            "reason": self.reason,
        }


def _filter_closed(tasks: Sequence[TaskSpec], closed_place_ids: set) -> tuple[list, list]:
    """返回 (剩余任务, 被关店杀死的必做任务id)。可选任务才允许被移除。"""
    filtered: List[TaskSpec] = []
    killed_required: List[str] = []
    for task in tasks:
        options = tuple(option for option in task.options
                        if option.place.id not in closed_place_ids)
        if not options:
            if task.required:
                killed_required.append(task.id)
            continue
        filtered.append(TaskSpec(
            id=task.id,
            options=options,
            required=task.required,
            precedence=task.precedence,
        ))
    return filtered, killed_required


def replan_tasks(*, tasks: Sequence[TaskSpec], completed_task_ids: Sequence[str],
                 current_node_id: str, current_time_seconds: float,
                 deadline_seconds: float, travel_time: TravelFn,
                 end_id: str = "H",
                 travel_source_kind: Optional[TravelSourceFn] = None,
                 walking_distance: Optional[TravelFn] = None,
                 events: Sequence[SimulationEvent] = (),
                 preference: str = "fastest",
                 max_alternatives: int = 3) -> ReplanResult:
    completed = set(completed_task_ids)
    remaining = [replace(task, precedence=tuple(
        predecessor for predecessor in task.precedence if predecessor not in completed
    )) for task in tasks if task.id not in completed]

    closed_places = {event.target_id for event in events if event.type == "close_place"}
    remaining, killed_required = _filter_closed(remaining, closed_places)
    if killed_required:
        reasons = {"REQUIRED_TASK_CLOSED": len(killed_required)}
        return ReplanResult(
            status="infeasible",
            plan=PlanResult("infeasible", infeasible_reasons=reasons,
                            suggestions=relaxation_suggestions(reasons)),
            locked_completed=list(completed),
            applied_events=[event.id for event in events],
            reason=f"REQUIRED_TASK_CLOSED:{','.join(killed_required)}",
        )
    all_tasks_completed = bool(tasks) and all(task.id in completed for task in tasks)
    if not remaining and not all_tasks_completed:
        return ReplanResult(
            status="infeasible",
            plan=PlanResult("infeasible", infeasible_reasons={"NO_REMAINING_TASKS": 1}),
            locked_completed=list(completed),
            applied_events=[event.id for event in events],
            reason="NO_REMAINING_TASKS",
        )

    delays: Dict[Tuple[str, str], float] = {}
    for event in events:
        if event.type == "route_delay":
            if "->" in event.target_id:
                frm, to = event.target_id.split("->", 1)
                delays[(frm, to)] = delays.get((frm, to), 0.0) + event.delay_seconds
            else:
                # target_id 视为目的地;该目的地所有进边延误。
                delays[("", event.target_id)] = delays.get(("", event.target_id), 0.0) + event.delay_seconds

    def delayed_time(frm: str, to: str) -> Optional[float]:
        base = travel_time(frm, to)
        if base is None:
            return None
        delay = delays.get((frm, to), 0.0) + delays.get(("", to), 0.0)
        return base + delay

    def delayed_source(frm: str, to: str) -> Optional[str]:
        delay = delays.get((frm, to), 0.0) + delays.get(("", to), 0.0)
        if delay > 0:
            return "synthetic-assumption"
        if travel_source_kind is not None:
            return travel_source_kind(frm, to)
        return "api-cache"

    if all_tasks_completed:
        walk_home = walking_distance(current_node_id, end_id) if walking_distance else None
        if preference == "least_walk" and walk_home is None:
            reasons = {"NO_WALK_DISTANCE": 1}
            return ReplanResult("infeasible", PlanResult(
                "infeasible", infeasible_reasons=reasons,
                suggestions=relaxation_suggestions(reasons)),
                locked_completed=list(completed), reason="NO_WALK_DISTANCE")
        return_seconds = delayed_time(current_node_id, end_id)
        if return_seconds is None:
            reasons = {"NO_RETURN_ROUTE": 1}
            return ReplanResult(
                status="infeasible",
                plan=PlanResult("infeasible", infeasible_reasons=reasons,
                                suggestions=relaxation_suggestions(reasons)),
                locked_completed=list(completed),
                applied_events=[event.id for event in events],
                reason="NO_RETURN_ROUTE",
            )
        finish_seconds = current_time_seconds + return_seconds
        if finish_seconds > deadline_seconds:
            reasons = {"DEADLINE": 1}
            return ReplanResult(
                status="infeasible",
                plan=PlanResult("infeasible", infeasible_reasons=reasons,
                                suggestions=relaxation_suggestions(reasons)),
                locked_completed=list(completed),
                applied_events=[event.id for event in events],
                reason="DEADLINE",
            )
        final_leg = Alternative(
            stops=[],
            finish_seconds=finish_seconds,
            total_travel_seconds=return_seconds,
            total_wait_seconds=0,
            total_service_seconds=0,
            departure_seconds=current_time_seconds,
            deadline_seconds=deadline_seconds,
            return_travel_seconds=return_seconds,
            return_travel_source_kind=delayed_source(current_node_id, end_id) or "unknown",
            total_walking_m=walk_home or 0,
            slack_seconds=deadline_seconds - finish_seconds,
        )
        return ReplanResult(
            status="ready",
            plan=PlanResult("ready", alternatives=[final_leg]),
            locked_completed=list(completed),
            applied_events=[event.id for event in events],
        )

    plan = plan_tasks(
        start_id=current_node_id,
        end_id=end_id,
        departure_seconds=current_time_seconds,
        deadline_seconds=deadline_seconds,
        tasks=remaining,
        travel_time=delayed_time,
        travel_source_kind=delayed_source,
        walking_distance=walking_distance,
        preference=preference,
        max_alternatives=max_alternatives,
    )
    return ReplanResult(
        status=plan.status,
        plan=plan,
        locked_completed=list(completed),
        applied_events=[event.id for event in events],
    )
