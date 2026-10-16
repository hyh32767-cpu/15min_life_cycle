# -*- coding: utf-8 -*-
"""时间窗口与场景时钟(纯函数,内部整数秒)。

契约:
- 演示时区固定 Asia/Shanghai;
- 服务完成时间 <= 关门时间 才算可完成,恰好关门通过;
- deadline 同理,恰好截止通过;
- 跨午夜窗口按 closes < opens 自动加一天;
- 营业时间未知不参与硬约束,由调用方显式处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Union
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SECONDS_PER_DAY = 86400

TimeLike = Union[int, float, datetime, str]


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TZ)
    return value.astimezone(TZ)


def parse_time(value: TimeLike, *, scene_start: datetime) -> int:
    """把 datetime/ISO/秒数统一为相对场景起点的整数秒。"""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise TypeError(f"不支持的时间类型: {type(value)!r}")
    base = ensure_aware(scene_start)
    return int((ensure_aware(value) - base).total_seconds())


def format_scene_time(seconds: int, *, scene_start: datetime) -> str:
    base = ensure_aware(scene_start)
    return (base + timedelta(seconds=int(seconds))).isoformat()


@dataclass(frozen=True)
class OpeningWindow:
    """可跨午夜的营业窗口(场景秒)。"""

    opens_seconds: int
    closes_seconds: int

    @classmethod
    def from_datetimes(cls, opens: datetime, closes: datetime, *, scene_start: datetime) -> "OpeningWindow":
        return cls(parse_time(opens, scene_start=scene_start),
                   parse_time(closes, scene_start=scene_start))

    @property
    def normalized(self) -> Tuple[int, int]:
        opens, closes = self.opens_seconds, self.closes_seconds
        if closes <= opens:
            closes += SECONDS_PER_DAY
        return opens, closes

    @property
    def crosses_midnight(self) -> bool:
        if self.closes_seconds <= self.opens_seconds:
            return True
        return (self.closes_seconds % SECONDS_PER_DAY) < (self.opens_seconds % SECONDS_PER_DAY)


@dataclass(frozen=True)
class ScheduleResult:
    feasible: bool
    start_seconds: Optional[int]
    finish_seconds: Optional[int]
    wait_seconds: int
    reason: str = ""


def schedule_in_window(now_seconds: int, service_seconds: int,
                       window: OpeningWindow) -> ScheduleResult:
    """早到等待;服务完成不得超过关门;恰好关门通过。"""
    if service_seconds < 0:
        raise ValueError("service_seconds 不能为负")
    opens, closes = window.normalized
    if now_seconds > closes:
        return ScheduleResult(False, None, None, 0, "CLOSED")
    start = max(now_seconds, opens)
    finish = start + service_seconds
    if finish > closes:
        return ScheduleResult(False, None, None, start - now_seconds, "CLOSED")
    return ScheduleResult(True, start, finish, start - now_seconds, "")


def meets_deadline(finish_seconds: int, deadline_seconds: int) -> bool:
    return finish_seconds <= deadline_seconds


def min_start_for_window(now_seconds: int, window: OpeningWindow) -> int:
    return max(now_seconds, window.normalized[0])


def is_open_at(now_seconds: int, window: OpeningWindow) -> bool:
    opens, closes = window.normalized
    return opens <= now_seconds <= closes
