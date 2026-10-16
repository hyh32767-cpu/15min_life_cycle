# -*- coding: utf-8 -*-
"""标准化百度 direction/matrix 为有方向 TravelLeg / TravelMatrix。

契约:
- 几何、时长、距离只来自同一条 direction 响应;
- matrix 只表示有方向 OD,缺失显式 no_route/error,不用直线补空;
- 来源逐项保留。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.baidu_client import route_leg_summary


@dataclass
class TravelLeg:
    from_id: str
    to_id: str
    duration_s: Optional[float]
    distance_m: Optional[float]
    status: str  # ok | no_route | error
    source_kind: str
    geometry: List[dict] = field(default_factory=list)
    steps: List[dict] = field(default_factory=list)
    route_ref: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.duration_s is not None


@dataclass
class TravelCell:
    from_index: int
    to_index: int
    duration_s: Optional[float]
    distance_m: Optional[float]
    status: str  # ok | no_route | error
    source_kind: str

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.duration_s is not None


@dataclass
class TravelMatrix:
    origin_ids: List[str]
    destination_ids: List[str]
    cells: List[TravelCell]
    source_kind: str

    def get(self, from_index: int, to_index: int) -> Optional[TravelCell]:
        for cell in self.cells:
            if cell.from_index == from_index and cell.to_index == to_index:
                return cell
        return None

    @property
    def complete(self) -> bool:
        return len(self.cells) == len(self.origin_ids) * len(self.destination_ids) \
            and all(cell.ok for cell in self.cells)


def direction_body_to_leg(body: Dict[str, Any], *, from_id: str, to_id: str,
                          source_kind: str = "live-api",
                          route_ref: Optional[str] = None) -> TravelLeg:
    routes = ((body.get("result") or {}).get("routes") or [])
    if not routes:
        return TravelLeg(from_id, to_id, None, None, "no_route", source_kind,
                         route_ref=route_ref)
    summary = route_leg_summary(routes[0])
    duration = summary.get("durationSeconds")
    distance = summary.get("distanceM")
    status = "ok" if duration is not None and distance is not None else "no_route"
    return TravelLeg(
        from_id=from_id,
        to_id=to_id,
        duration_s=duration,
        distance_m=distance,
        status=status,
        source_kind=source_kind,
        geometry=summary.get("geometry") or [],
        steps=summary.get("steps") or [],
        route_ref=route_ref,
    )


def matrix_body_to_matrix(body: Dict[str, Any], *, origin_ids: List[str],
                          destination_ids: List[str],
                          source_kind: str = "live-api") -> TravelMatrix:
    raw_items = body.get("result") or []
    cells: List[TravelCell] = []
    n_dest = len(destination_ids)
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        from_index, to_index = divmod(index, n_dest) if n_dest else (0, 0)
        duration = (item.get("duration") or {}).get("value")
        distance = (item.get("distance") or {}).get("value")
        status = "ok" if duration is not None and distance is not None else "no_route"
        cells.append(TravelCell(from_index, to_index, duration, distance, status, source_kind))
    # 缺失条目显式补 no_route,避免调用方把空缺当零。
    existing = {(c.from_index, c.to_index) for c in cells}
    for oi in range(len(origin_ids)):
        for di in range(len(destination_ids)):
            if (oi, di) not in existing:
                cells.append(TravelCell(oi, di, None, None, "error", source_kind))
    cells.sort(key=lambda c: (c.from_index, c.to_index))
    return TravelMatrix(origin_ids=list(origin_ids),
                        destination_ids=list(destination_ids),
                        cells=cells, source_kind=source_kind)
