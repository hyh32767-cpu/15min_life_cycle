"""沿线路径的稀疏采样与完整测时圈并集；不推断缺测区或绕行可行性。"""
import math

from shapely import constrained_delaunay_triangles, union_all
from shapely.geometry import Polygon

from core.coord import dest_at, haversine


def route_centers(points: list[dict], max_centers: int = 5) -> dict:
    """选已有路线顶点，不把邻近格点冒充路线中心；反向使用同一组顶点。"""
    unique = []
    for point in points:
        value = (float(point['lng']), float(point['lat']))
        if not unique or value != unique[-1]:
            unique.append(value)
    reverse = tuple(unique) > tuple(reversed(unique))
    ordered = list(reversed(unique)) if reverse else unique
    distances = [0.0]
    for a, b in zip(ordered, ordered[1:]):
        distances.append(distances[-1] + haversine(*a, *b))
    total = distances[-1]
    count = min(max_centers, max(2, math.ceil(total / 800) + 1), len(ordered))
    indices = {min(range(len(ordered)), key=lambda i: (abs(distances[i] - target), ordered[i], i))
               for target in ([total * i / (count - 1) for i in range(count)] if count > 1 else [0])}
    selected = [(ordered[i], distances[i]) for i in sorted(indices)]
    if reverse:
        selected = [(point, total - distance) for point, distance in reversed(selected)]
    return {'centers': [{'lng': p[0], 'lat': p[1], 'crs': 'BD09'} for p, _ in selected],
            'distanceM': total,
            'maxGapM': max((b[1] - a[1] for a, b in zip(selected, selected[1:])), default=0)}


def union_circles(circles: list[dict]) -> dict:
    polygons = []
    for circle in circles:
        if circle['status'] != 'complete':
            continue
        if circle.get('frontier'):
            for part in circle['frontier']['polygons']:
                ring = lambda values: [(p['lng'], p['lat']) for p in values]
                polygon = Polygon(ring(part['outer']), [ring(h) for h in part['holes']])
                if polygon.is_valid and polygon.area > 0:
                    polygons.append(polygon)
            continue
        origin = circle['origin']
        rays = sorted((float(b), float(r)) for b, r in circle['radiiM'].items())
        if len(rays) < 3 or any(not math.isfinite(r) or r <= 0 for _, r in rays):
            continue
        ring = []
        for bearing, radius in rays:
            lat, lng = dest_at(origin['lng'], origin['lat'], bearing, radius)
            ring.append((lng, lat))
        polygon = Polygon(ring)
        if polygon.is_valid and polygon.area > 0:
            polygons.append(polygon)
    merged = union_all(polygons)
    pieces = [merged] if merged.geom_type == 'Polygon' else list(getattr(merged, 'geoms', []))
    fills, boundaries = [], []

    def coords(ring):
        return [{'lng': x, 'lat': y, 'crs': 'BD09'} for x, y in ring.coords]

    for polygon in pieces:
        if polygon.is_empty or polygon.geom_type != 'Polygon':
            continue
        boundaries.append(coords(polygon.exterior))
        boundaries.extend(coords(hole) for hole in polygon.interiors)
        # 百度单环 Polygon 无孔洞接口；约束三角剖分保留孔洞，不填桥梁/障碍空缺。
        if polygon.interiors:
            fills.extend(coords(triangle.exterior)
                         for triangle in constrained_delaunay_triangles(polygon).geoms)
        else:
            fills.append(coords(polygon.exterior))
    return {'fills': fills, 'boundaries': boundaries}
