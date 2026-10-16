# -*- coding: utf-8 -*-
"""走廊几何纯函数:按距离采样路线中心、点到折线距离。

只用于召回窗口和预筛,不用于计算最终绕行时间。
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

from core.coord import haversine

Point = Tuple[float, float]  # (lng, lat)
_M_PER_DEG = 111320.0


def polyline_length_m(points: Sequence[Point]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += haversine(a[0], a[1], b[0], b[1])
    return total


def _interpolate(points: Sequence[Point], target_m: float) -> Point:
    if not points:
        raise ValueError("points 不能为空")
    if len(points) == 1:
        return points[0]
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        seg = haversine(a[0], a[1], b[0], b[1])
        if seg <= 0:
            continue
        if travelled + seg >= target_m:
            ratio = (target_m - travelled) / seg
            return (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)
        travelled += seg
    return points[-1]


def sample_centers(points: Sequence[Point], *, spacing_m: float,
                   radius_m: float) -> List[Point]:
    if len(points) < 2:
        return list(points)
    if spacing_m <= 0:
        spacing_m = radius_m
    total = polyline_length_m(points)
    if total <= 0:
        return [points[0]]
    centers: List[Point] = []
    distance = 0.0
    while distance <= total:
        centers.append(_interpolate(points, distance))
        distance += spacing_m
    if centers[-1] != points[-1]:
        centers.append(points[-1])
    return centers


def point_to_segment_m(p: Point, a: Point, b: Point) -> float:
    """局部等距投影下的点到线段距离(米),2km 尺度误差可忽略。"""
    lat_ref = math.radians((a[1] + b[1]) / 2.0)
    bx = (b[0] - a[0]) * _M_PER_DEG * math.cos(lat_ref)
    by = (b[1] - a[1]) * _M_PER_DEG
    px = (p[0] - a[0]) * _M_PER_DEG * math.cos(lat_ref)
    py = (p[1] - a[1]) * _M_PER_DEG
    ab2 = bx * bx + by * by
    if ab2 <= 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / ab2))
    return math.hypot(px - bx * t, py - by * t)


def point_to_polyline_m(p: Point, points: Sequence[Point]) -> float:
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine(p[0], p[1], points[0][0], points[0][1])
    return min(point_to_segment_m(p, a, b) for a, b in zip(points, points[1:]))


def dedupe_points(points: Iterable[Point], *, precision: int = 6) -> List[Point]:
    seen = set()
    out: List[Point] = []
    for lng, lat in points:
        key = (round(lng, precision), round(lat, precision))
        if key not in seen:
            seen.add(key)
            out.append((lng, lat))
    return out
