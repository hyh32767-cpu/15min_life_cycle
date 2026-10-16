"""Delaunay线性时间场的等值线；仅消费实测探针，无网络、无视觉样条。

保留射线主多边形作为判定层。这里输出实验中的重建场显示层，超出
该向射线半径80m的部分裁掉；开口线不擅自闭合成可达区域。
直接在三角网中抽线，不经过历史实验的50m栅格重采样。
"""
import math
from collections import Counter

from core.coord import dest_at

VERSION = 'delaunay-linear-contour-v1'


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _inside_circle(a, b, c, p):
    ax, ay = a[0] - p[0], a[1] - p[1]
    bx, by = b[0] - p[0], b[1] - p[1]
    cx, cy = c[0] - p[0], c[1] - p[1]
    determinant = ((ax * ax + ay * ay) * (bx * cy - by * cx)
                   - (bx * bx + by * by) * (ax * cy - ay * cx)
                   + (cx * cx + cy * cy) * (ax * by - ay * bx))
    return determinant * (1 if _orient(a, b, c) > 0 else -1) > 1e-12


def _triangles(points):
    n = len(points)
    scale = max(1, max(math.hypot(x, y) for x, y, _ in points))
    vertices = [(x / scale, y / scale) for x, y, _ in points] + [(-20, -10), (20, -10), (0, 20)]
    triangles = [(n, n + 1, n + 2)]
    for i in range(n):
        bad = [t for t in triangles if _inside_circle(*(vertices[j] for j in t), vertices[i])]
        edges = Counter(tuple(sorted(e)) for a, b, c in bad for e in ((a, b), (b, c), (c, a)))
        rejected = set(bad)
        triangles = [t for t in triangles if t not in rejected]
        triangles.extend((a, b, i) for (a, b), count in edges.items()
                         if count == 1 and abs(_orient(vertices[a], vertices[b], vertices[i])) > 1e-12)
    return [t for t in triangles if max(t) < n]


def _join(segments):
    def key(p):
        return round(p[0], 5), round(p[1], 5)
    edges = {}
    positions = {}
    for a, b in segments:
        ka, kb = key(a), key(b)
        if ka == kb:
            continue
        positions[ka], positions[kb] = a, b
        edges.setdefault(ka, set()).add(kb)
        edges.setdefault(kb, set()).add(ka)
    lines = []
    while any(edges.values()):
        start = next((k for k, v in edges.items() if len(v) == 1), None)
        if start is None:
            start = next(k for k, v in edges.items() if v)
        line, current = [positions[start]], start
        while edges[current]:
            nxt = min(edges[current])
            edges[current].remove(nxt)
            edges[nxt].remove(current)
            line.append(positions[nxt])
            current = nxt
            if current == start:
                break
        lines.append(line)
    return lines


def reconstruct_time_contours(samples, radii, *, threshold_s, lng, lat):
    """samples为(bearing, distance, seconds)，未知/无效测值不参加重建。"""
    unique = {}
    for bearing, distance, duration in samples:
        if duration is None or not all(math.isfinite(v) for v in (bearing, distance, duration)) or distance < 0 or duration < 0:
            continue
        angle = math.radians(bearing)
        point = round(math.sin(angle) * distance, 7), round(math.cos(angle) * distance, 7)
        # 同点有不同测值时取较大的时间，不制造更快的通行证据。
        unique[point] = max(unique.get(point, duration), duration)
    points = [(x, y, t) for (x, y), t in sorted(unique.items())]
    result = {'method': VERSION, 'sampleCount': len(points), 'contours': [],
              'clipMarginM': 80, 'classificationBoundary': 'ray-polygon',
              'note': '全部有效探针重建的线性时间等值线；非完整路网边界，覆盖判定仍使用射线主多边形'}
    if len(points) < 3 or len(radii) < 3:
        return result
    segments = []
    for triangle in _triangles(points):
        hits = []
        for ia, ib in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
            a, b = points[ia], points[ib]
            if (a[2] <= threshold_s) == (b[2] <= threshold_s):
                continue
            ratio = (threshold_s - a[2]) / (b[2] - a[2])
            hits.append((a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])))
        if len(hits) == 2:
            segments.append(hits)
    normalized = {}
    for bearing, radius in radii.items():
        if radius is None or not math.isfinite(float(radius)) or float(radius) < 0:
            continue
        bearing = float(bearing) % 360
        normalized[bearing] = min(normalized.get(bearing, float(radius)), float(radius))
    angles = sorted(normalized.items())
    if len(angles) < 3:
        return result

    def allowed(p):
        bearing = math.degrees(math.atan2(p[0], p[1])) % 360
        for i, (a, ra) in enumerate(angles):
            b, rb = angles[(i + 1) % len(angles)]
            gap = (b - a) % 360
            offset = (bearing - a) % 360
            if offset <= gap:
                boundary = ra + (rb - ra) * offset / gap
                return math.hypot(*p) <= boundary + 80
        return False

    clipped = []
    for line in _join(segments):
        current = []
        for a, b in zip(line, line[1:]):
            steps = max(1, math.ceil(math.dist(a, b) / 10))
            for i in range(steps):
                p = (a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)
                if allowed(p):
                    current.append(p)
                elif current:
                    if len(current) > 1:
                        clipped.append(current)
                    current = []
        if allowed(line[-1]):
            current.append(line[-1])
        if len(current) > 1:
            clipped.append(current)
    for line in clipped:
        ring = []
        for x, y in line:
            la, ln = dest_at(lng, lat, math.degrees(math.atan2(x, y)), math.hypot(x, y))
            ring.append({'lng': ln, 'lat': la, 'crs': 'BD09'})
        result['contours'].append(ring)
    return result
