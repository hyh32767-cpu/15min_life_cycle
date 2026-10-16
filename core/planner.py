# -*- coding: utf-8 -*-
"""多任务时间窗规划内核(纯函数)。

docs/19 §9:
- 2—5 个任务,每个任务固定 POI 或少量候选;
- 枚举候选选择和满足 precedence 的任务顺序;
- 早到可等待,服务完成 <= 关门;必须计入最后返程;
- 业务 OD 由调用方注入,缺失路径显式 reject,不用直线补空。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from core.timewindow import OpeningWindow, schedule_in_window

TravelFn = Callable[[str, str], Optional[float]]
TravelSourceFn = Callable[[str, str], Optional[str]]


@dataclass(frozen=True)
class PlaceNode:
    id: str
    name: str = ""


@dataclass(frozen=True)
class TaskOption:
    task_id: str
    place: PlaceNode
    service_seconds: int = 0
    window: Optional[OpeningWindow] = None
    windows: Tuple[OpeningWindow, ...] = ()
    service_source_kind: str = "user-input"
    window_source_kind: str = "unknown"


@dataclass(frozen=True)
class TaskSpec:
    id: str
    options: Tuple[TaskOption, ...]
    required: bool = True
    precedence: Tuple[str, ...] = ()


@dataclass
class PlanStop:
    task_id: str
    place_id: str
    arrival_seconds: float
    start_seconds: float
    finish_seconds: float
    wait_seconds: float
    travel_seconds: float
    travel_source_kind: str = "api-cache"
    service_source_kind: str = "user-input"
    window_source_kind: str = "unknown"


@dataclass
class Alternative:
    stops: List[PlanStop]
    finish_seconds: float
    total_travel_seconds: float
    total_wait_seconds: float
    total_service_seconds: float
    total_walking_m: float = 0.0
    departure_seconds: float = 0.0
    deadline_seconds: float = 0.0
    return_travel_seconds: float = 0.0
    return_travel_source_kind: str = "api-cache"
    slack_seconds: float = 0.0
    sequence_key: Tuple[str, ...] = field(default_factory=tuple, repr=False)

    @property
    def sequence(self) -> Tuple[str, ...]:
        if self.sequence_key:
            return self.sequence_key
        return tuple(f"{stop.task_id}:{stop.place_id}" for stop in self.stops)

    def _timeline(self) -> List[dict]:
        timeline: List[dict] = [
            {"kind": "departure", "seconds": self.departure_seconds, "sourceKind": "user-input"},
        ]
        for stop in self.stops:
            timeline.append({
                "kind": "travel", "taskId": stop.task_id, "toPlaceId": stop.place_id,
                "durationSeconds": stop.travel_seconds,
                "sourceKind": stop.travel_source_kind,
            })
            timeline.append({
                "kind": "arrival", "taskId": stop.task_id,
                "seconds": stop.arrival_seconds, "sourceKind": "derived",
            })
            if stop.wait_seconds > 0:
                timeline.append({
                    "kind": "wait", "taskId": stop.task_id,
                    "durationSeconds": stop.wait_seconds,
                    "sourceKind": stop.window_source_kind,
                })
            timeline.append({
                "kind": "service", "taskId": stop.task_id,
                "durationSeconds": stop.finish_seconds - stop.start_seconds,
                "sourceKind": stop.service_source_kind,
            })
            timeline.append({
                "kind": "taskFinish", "taskId": stop.task_id,
                "seconds": stop.finish_seconds, "sourceKind": "derived",
            })
        timeline.append({
            "kind": "returnTravel",
            "durationSeconds": self.return_travel_seconds,
            "sourceKind": self.return_travel_source_kind,
        })
        timeline.append({
            "kind": "homeArrival", "seconds": self.finish_seconds,
            "sourceKind": "derived",
        })
        timeline.append({
            "kind": "deadline", "seconds": self.deadline_seconds,
            "slackSeconds": self.slack_seconds, "sourceKind": "user-input",
        })
        return timeline

    def as_dict(self) -> dict:
        return {
            "stops": [
                {
                    "taskId": stop.task_id,
                    "placeId": stop.place_id,
                    "arrivalSeconds": stop.arrival_seconds,
                    "startSeconds": stop.start_seconds,
                    "finishSeconds": stop.finish_seconds,
                    "waitSeconds": stop.wait_seconds,
                    "travelSeconds": stop.travel_seconds,
                    "travelSourceKind": stop.travel_source_kind,
                    "serviceSourceKind": stop.service_source_kind,
                    "windowSourceKind": stop.window_source_kind,
                }
                for stop in self.stops
            ],
            "timeline": self._timeline(),
            "departureSeconds": self.departure_seconds,
            "finishSeconds": self.finish_seconds,
            "deadlineSeconds": self.deadline_seconds,
            "slackSeconds": self.slack_seconds,
            "totalTravelSeconds": self.total_travel_seconds,
            "totalWaitSeconds": self.total_wait_seconds,
            "totalServiceSeconds": self.total_service_seconds,
            "totalWalkingM": self.total_walking_m,
            "returnTravelSeconds": self.return_travel_seconds,
            "returnTravelSourceKind": self.return_travel_source_kind,
        }


@dataclass
class PlanResult:
    status: str  # ready | infeasible
    alternatives: List[Alternative] = field(default_factory=list)
    infeasible_reasons: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "alternatives": [alt.as_dict() for alt in self.alternatives],
            "infeasibleReasons": self.infeasible_reasons,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


_RELAXATION_HINTS = {
    "OD_UNAVAILABLE": "部分路段缺百度测时（配额/网络/缓存缺失）：稍后重试或先换已测路段",
    "NO_ROUTE": "更换候选 POI 或改用其他交通方式",
    "NO_RETURN_ROUTE": "选择更接近返程节点的候选",
    "DEADLINE": "延后最晚到家时间或缩短任务服务时长",
    "CLOSED": "放宽营业时间或更换候选门店",
    "EXTRA_BUDGET": "提高额外路程预算或更换更顺路的候选",
    "PRECEDENCE_CYCLE": "检查任务先后依赖是否互相冲突",
    "NO_OPTIONS": "为任务补充至少一个候选地点",
    "NO_WALK_DISTANCE": "补充百度矩阵步行距离,或改用最快目标",
    "NO_SOLUTION": "放宽预算/时间窗,或减少必须任务",
    "REQUIRED_TASK_CLOSED": "被关闭的必做任务无可替候选：换一家店，或将其改为可选后重排",
}


def relaxation_suggestions(reasons: Dict[str, int]) -> List[str]:
    """把无解原因转成用户可接受的放宽建议,不自动删任务。"""
    return [_RELAXATION_HINTS[key] for key in reasons if key in _RELAXATION_HINTS]


def _valid_orders(tasks: Sequence[TaskSpec]) -> List[Tuple[TaskSpec, ...]]:
    ids = {task.id: task for task in tasks}
    orders: List[Tuple[TaskSpec, ...]] = []
    for permutation in itertools.permutations(tasks):
        positions = {task.id: index for index, task in enumerate(permutation)}
        valid = True
        for task in permutation:
            for predecessor in task.precedence:
                if predecessor not in ids:
                    valid = False
                    break
                if positions[predecessor] >= positions[task.id]:
                    valid = False
                    break
            if not valid:
                break
        if valid:
            orders.append(permutation)
    return orders


def _reject(reasons: Dict[str, int], reason: str) -> None:
    reasons[reason] = reasons.get(reason, 0) + 1


def plan_tasks(*, start_id: str, end_id: str, departure_seconds: float,
               deadline_seconds: float, tasks: Sequence[TaskSpec],
               travel_time: TravelFn, max_alternatives: int = 3,
               preference: str = "fastest",
               walking_distance: Optional[TravelFn] = None,
               travel_source_kind: Optional[TravelSourceFn] = None) -> PlanResult:
    if preference not in {"fastest", "least_walk"}:
        raise ValueError("preference 只能是 fastest 或 least_walk")
    if not tasks:
        return PlanResult("infeasible", infeasible_reasons={"NO_TASKS": 1},
                          suggestions=relaxation_suggestions({"NO_TASKS": 1}))
    if len(tasks) > 5:
        raise ValueError("P0 最多 5 个任务")
    if any(not task.options for task in tasks):
        return PlanResult("infeasible", infeasible_reasons={"NO_OPTIONS": 1},
                          suggestions=relaxation_suggestions({"NO_OPTIONS": 1}))

    required_tasks = [task for task in tasks if task.required]
    optional_tasks = [task for task in tasks if not task.required]
    if not required_tasks and not optional_tasks:
        return PlanResult("infeasible", infeasible_reasons={"NO_TASKS": 1},
                          suggestions=relaxation_suggestions({"NO_TASKS": 1}))

    def subset_keeps_precedence(subset: Sequence[TaskSpec]) -> bool:
        included = {task.id for task in subset}
        for task in subset:
            for predecessor in task.precedence:
                if predecessor not in included:
                    return False
        return True

    # 必做始终加入；可选枚举全部子集（含空集），前置缺失的子集丢弃。
    # 后继依赖被跳任务时连带跳过——由 subset_keeps_precedence 保证。
    optional_subsets: List[Tuple[TaskSpec, ...]] = []
    for r in range(len(optional_tasks) + 1):
        for combo in itertools.combinations(optional_tasks, r):
            candidate = tuple(required_tasks) + tuple(combo)
            if subset_keeps_precedence(candidate):
                optional_subsets.append(tuple(candidate))
    # 子集越大越优先：同一目标下多做可选任务。
    optional_subsets.sort(key=lambda subset: len(subset), reverse=True)

    orders_cache: Dict[Tuple[str, ...], List[Tuple[TaskSpec, ...]]] = {}

    def orders_for(subset: Sequence[TaskSpec]) -> List[Tuple[TaskSpec, ...]]:
        key = tuple(task.id for task in subset)
        if key not in orders_cache:
            orders_cache[key] = _valid_orders(subset)
        return orders_cache[key]

    reasons: Dict[str, int] = {}
    best_by_sequence: Dict[Tuple[str, ...], Alternative] = {}
    for subset in optional_subsets:
        orders = orders_for(subset)
        if not orders:
            _reject(reasons, "PRECEDENCE_CYCLE")
            continue
        for assignment in itertools.product(*[task.options for task in subset]):
            option_by_task = {option.task_id: option for option in assignment}
            for order in orders:
                now = float(departure_seconds)
                at = start_id
                stops: List[PlanStop] = []
                total_travel = total_wait = total_service = total_walk = 0.0
                feasible = True
                for task in order:
                    option = option_by_task[task.id]
                    leg = travel_time(at, option.place.id)
                    if leg is None:
                        _reject(reasons, "NO_ROUTE")
                        feasible = False
                        break
                    arrival = now + float(leg)
                    total_travel += float(leg)
                    if preference == "least_walk":
                        walk = walking_distance(at, option.place.id) if walking_distance else None
                        if walk is None:
                            _reject(reasons, "NO_WALK_DISTANCE")
                            feasible = False
                            break
                        total_walk += float(walk)
                    candidate_windows = list(option.windows) + (
                        [option.window] if option.window is not None else [])
                    if candidate_windows:
                        best_schedule = None
                        best_reason = "CLOSED"
                        for candidate in candidate_windows:
                            schedule = schedule_in_window(int(arrival), int(option.service_seconds),
                                                        candidate)
                            if schedule.feasible and (
                                    best_schedule is None
                                    or schedule.finish_seconds < best_schedule.finish_seconds):
                                best_schedule = schedule
                        if best_schedule is None:
                            _reject(reasons, best_reason)
                            feasible = False
                            break
                        start = float(best_schedule.start_seconds)
                        finish = float(best_schedule.finish_seconds)
                        wait = float(best_schedule.wait_seconds)
                    else:
                        start = arrival
                        finish = arrival + option.service_seconds
                        wait = 0.0
                    total_wait += wait
                    total_service += option.service_seconds
                    stops.append(PlanStop(
                        task_id=task.id,
                        place_id=option.place.id,
                        arrival_seconds=arrival,
                        start_seconds=start,
                        finish_seconds=finish,
                        wait_seconds=wait,
                        travel_seconds=float(leg),
                        travel_source_kind=(
                            travel_source_kind(at, option.place.id)
                            if travel_source_kind else "api-cache"
                        ) or "api-cache",
                        service_source_kind=option.service_source_kind,
                        window_source_kind=option.window_source_kind,
                    ))
                    now = finish
                    at = option.place.id
                if not feasible:
                    continue
                back = travel_time(at, end_id)
                if back is None:
                    _reject(reasons, "NO_RETURN_ROUTE")
                    continue
                back_source = (travel_source_kind(at, end_id) if travel_source_kind else "api-cache")
                now += float(back)
                total_travel += float(back)
                if preference == "least_walk":
                    walk_back = walking_distance(at, end_id) if walking_distance else None
                    if walk_back is None:
                        _reject(reasons, "NO_WALK_DISTANCE")
                        continue
                    total_walk += float(walk_back)
                if now > deadline_seconds:
                    _reject(reasons, "DEADLINE")
                    continue
                alternative = Alternative(
                    stops=stops,
                    finish_seconds=now,
                    total_travel_seconds=total_travel,
                    total_wait_seconds=total_wait,
                    total_service_seconds=total_service,
                    total_walking_m=total_walk,
                    departure_seconds=float(departure_seconds),
                    deadline_seconds=float(deadline_seconds),
                    return_travel_seconds=float(back),
                    return_travel_source_kind=back_source or "api-cache",
                    slack_seconds=float(deadline_seconds) - now,
                )
                alternative.sequence_key = tuple(
                    f"{stop.task_id}:{stop.place_id}" for stop in alternative.stops)
                key = alternative.sequence
                current = best_by_sequence.get(key)
                if current is None or (alternative.finish_seconds, alternative.total_travel_seconds) < \
                    (current.finish_seconds, current.total_travel_seconds):
                        best_by_sequence[key] = alternative
    if not best_by_sequence:
        reasons = reasons or {"NO_SOLUTION": 1}
        return PlanResult("infeasible", infeasible_reasons=reasons,
                          suggestions=relaxation_suggestions(reasons))
    # T212：营业时间未知不作为硬约束，但必须让用户分清“确认营业”与“未知未限”；
    # warnings 只收敛到最终方案实际 stops（不把未选中候选/未选中子集的未知全抖出来）。
    if preference == "least_walk":
        sorted_alts = sorted(
            best_by_sequence.values(),
            key=lambda alt: (-len(alt.stops), alt.total_walking_m, alt.finish_seconds,
                             alt.total_travel_seconds, alt.sequence),
        )
    else:
        sorted_alts = sorted(
            best_by_sequence.values(),
            key=lambda alt: (-len(alt.stops), alt.finish_seconds, alt.total_travel_seconds, alt.sequence),
        )
    deduped: List[Alternative] = []
    seen_sequences = set()
    for alt in sorted_alts:
        if alt.sequence not in seen_sequences:
            seen_sequences.add(alt.sequence)
            deduped.append(alt)
    chosen = deduped[:max_alternatives]
    unknown_labels = sorted({
        f"UNKNOWN_HOURS:{stop.task_id}:{stop.place_id}"
        for alt in chosen
        for stop in alt.stops
        if stop.window_source_kind == "unknown"
    })
    return PlanResult("ready", alternatives=chosen,
                      infeasible_reasons=reasons, warnings=unknown_labels)
