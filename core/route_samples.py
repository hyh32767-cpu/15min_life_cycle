# -*- coding: utf-8 -*-
"""基准步行路线按距离抽样,并保留步骤前缀耗时。

输入百度 direction 原始 body。几何来自步骤 path(API),时间来自步骤
duration(API);中间插值点的前缀时间标记为 derived。路线响应变化时调用方
必须重新抽样。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.coord import haversine


@dataclass
class RouteSample:
    lng: float
    lat: float
    prefix_seconds: float
    source_kind: str
    time_source_kind: str = "derived"
    crs: str = "BD09"
    distance_m: float = 0.0


def _parse_path(path: str) -> List[tuple]:
    points: List[tuple] = []
    for pair in str(path or "").split(";"):
        parts = pair.split(",")
        if len(parts) >= 2:
            try:
                points.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    return points


def _step_vertices(route: Dict[str, Any]) -> List[Dict[str, float]]:
    """把每个 step 的 path 展平,并给出累计距离/累计时间(API 步骤值)。"""
    vertices: List[Dict[str, float]] = []
    cumulative_distance = 0.0
    cumulative_time = 0.0
    for step in route.get("steps") or []:
        points = _parse_path(step.get("path") or "")
        if not points:
            continue
        step_distance = float(step.get("distance") or 0.0)
        step_duration = float(step.get("duration") or 0.0)
        local_cum = 0.0
        for index, (lng, lat) in enumerate(points):
            if index > 0:
                local_cum += haversine(points[index - 1][0], points[index - 1][1], lng, lat)
            if step_distance > 0:
                ratio = min(1.0, local_cum / step_distance)
            else:
                ratio = index / max(1, len(points) - 1)
            vertices.append({
                "lng": lng,
                "lat": lat,
                "distance": cumulative_distance + ratio * step_distance,
                "time": cumulative_time + ratio * step_duration,
            })
        cumulative_distance += step_distance
        cumulative_time += step_duration
    return vertices


def _interpolate(vertices: List[Dict[str, float]], target_distance: float) -> Dict[str, float]:
    if not vertices:
        raise ValueError("route 没有可用 path")
    if target_distance <= 0:
        return vertices[0]
    for a, b in zip(vertices, vertices[1:]):
        if a["distance"] <= target_distance <= b["distance"]:
            span = b["distance"] - a["distance"]
            ratio = 0.0 if span <= 0 else (target_distance - a["distance"]) / span
            return {
                "lng": a["lng"] + (b["lng"] - a["lng"]) * ratio,
                "lat": a["lat"] + (b["lat"] - a["lat"]) * ratio,
                "distance": target_distance,
                "time": a["time"] + (b["time"] - a["time"]) * ratio,
            }
    return vertices[-1]


def sample_direction_body(body: Dict[str, Any], *, sample_m: float = 200.0,
                          source_kind: str = "live-api") -> List[RouteSample]:
    if sample_m <= 0:
        raise ValueError("sample_m 必须大于 0")
    routes = ((body.get("result") or {}).get("routes") or [])
    if not routes:
        return []
    route = routes[0]
    vertices = _step_vertices(route)
    if not vertices:
        return []
    total = float(route.get("distance") or vertices[-1]["distance"])
    distances: List[float] = []
    d = 0.0
    while d < total:
        distances.append(round(d, 6))
        d += sample_m
    if not distances or distances[-1] < total:
        distances.append(total)

    samples: List[RouteSample] = []
    for target in distances:
        point = _interpolate(vertices, target)
        samples.append(RouteSample(
            lng=float(point["lng"]),
            lat=float(point["lat"]),
            prefix_seconds=float(point["time"]),
            source_kind=source_kind,
            distance_m=float(target),
        ))
    return samples


def sample_geometry(geometry: List[Dict[str, Any]], *, total_duration_s: float,
                    sample_m: float = 200.0,
                    source_kind: str = "api-cache") -> List[RouteSample]:
    """从已展平几何 + API 总时长抽样;前缀时间按距离比例,标记 derived。

    用于路线采样点→POI 的接入证据;prefix 不是新 API 响应,而是从同一
    direction 总时长推导的时间标签。
    """
    points = []
    for item in geometry:
        if item.get("lng") is not None and item.get("lat") is not None:
            points.append((float(item["lng"]), float(item["lat"])))
    if len(points) < 2:
        return []
    vertices = []
    cumulative = 0.0
    for index, (lng, lat) in enumerate(points):
        if index > 0:
            cumulative += haversine(points[index - 1][0], points[index - 1][1], lng, lat)
        vertices.append({"lng": lng, "lat": lat, "distance": cumulative, "time": cumulative})
    total = cumulative
    if total <= 0:
        return []
    for vertex in vertices:
        vertex["time"] = total_duration_s * (vertex["distance"] / total)

    samples: List[RouteSample] = []
    distance = 0.0
    while distance <= total:
        point = _interpolate(vertices, distance)
        samples.append(RouteSample(
            lng=float(point["lng"]),
            lat=float(point["lat"]),
            prefix_seconds=float(point["time"]),
            source_kind=source_kind,
            distance_m=float(distance),
        ))
        distance += sample_m
    last = _interpolate(vertices, total)
    samples.append(RouteSample(
        lng=float(last["lng"]),
        lat=float(last["lat"]),
        prefix_seconds=float(last["time"]),
        source_kind=source_kind,
        distance_m=float(total),
    ))
    return samples
