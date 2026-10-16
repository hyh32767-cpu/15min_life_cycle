"""外向内自适应网格实验引擎；查询回调之外不可访问参考场，无网络依赖。"""
from __future__ import annotations

import math


def outside_in(oracle, *, half=500, spacing=50, budget=300,
               thresholds=(900, 600, 300), near_seconds=120):
    if spacing <= 0 or half <= 0 or half % spacing or budget < 1:
        raise ValueError('half必须对齐spacing且budget为正')
    coarse = 4 * spacing
    inner_extent = ((half - 1) // coarse) * coarse
    axis = sorted(set([-half, half, 0] + list(range(-inner_extent, inner_extent + 1, coarse))))
    axis = [v for v in axis if -half <= v <= half]
    observed, phases = {}, []
    anchor = (0, 0)

    def read(points, phase):
        fresh = sorted(set(points) - set(observed), key=lambda p: (-max(abs(p[0]), abs(p[1])), p))
        count = min(len(fresh), max(0, budget - len(observed)))
        for p in fresh[:count]:
            value = oracle(*p)
            observed[p] = float(value) if value is not None and math.isfinite(value) and value > 0 else None
        phases.append({'phase': phase, 'newQueries': count, 'queries': len(observed)})

    def corners(cell):
        x0, y0, x1, y1 = cell
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def mid(a, b):
        if b - a <= spacing:
            return None
        return max(a + spacing, min(b - spacing, round((a + b) / (2 * spacing)) * spacing))

    def center(cell):
        x0, y0, x1, y1 = cell
        x, y = mid(x0, x1), mid(y0, y1)
        return (x, y) if x is not None and y is not None else None

    def value(p):
        return 0.0 if p == anchor else observed.get(p)

    initial = [(x, y) for x in axis for y in axis if (x, y) != anchor]
    read(initial, 'outer-first-coarse')
    leaves = [(a, c, b, d) for a, b in zip(axis, axis[1:]) for c, d in zip(axis, axis[1:])]
    read([p for cell in leaves if (p := center(cell)) and p != anchor], 'interior-sentinels')

    def risk(cell):
        vals = [value(p) for p in corners(cell)]
        if any(v is None for v in vals):
            return 0, 'unknown'
        p = center(cell)
        cv = value(p) if p else None
        all_values = vals + ([cv] if cv is not None else [])
        for i, t in enumerate(thresholds):
            if min(all_values) <= t < max(all_values):
                return (10 if i == 0 else 6 - i), f'crossing-{t}'
        if cv is not None and abs(cv - sum(vals) / 4) > near_seconds:
            return 7, 'interior-residual'
        if any(abs(v - t) <= near_seconds for v in all_values for t in thresholds):
            return 2, 'near-threshold'
        return 0, 'estimated-interior'

    blocked = set()
    while len(observed) < budget:
        queue = [(risk(c)[0], max(map(abs, c)), c) for c in leaves
                 if c not in blocked and (c[2] - c[0] > spacing or c[3] - c[1] > spacing)]
        queue = sorted((q for q in queue if q[0]), reverse=True)
        if not queue:
            break
        _, _, cell = queue[0]
        x0, y0, x1, y1 = cell
        mx, my = mid(x0, x1), mid(y0, y1)
        xs = [x0] + ([mx] if mx is not None else []) + [x1]
        ys = [y0] + ([my] if my is not None else []) + [y1]
        children = [(a, c, b, d) for a, b in zip(xs, xs[1:]) for c, d in zip(ys, ys[1:])]
        # 边界外一格保护带，全部对齐基础网格。
        required = {p for child in children for p in corners(child)}
        for child in children:
            if (p := center(child)):
                required.add(p)
        if risk(cell)[1].startswith('crossing'):
            for x, y in list(required):
                for dx, dy in ((spacing, 0), (-spacing, 0), (0, spacing), (0, -spacing)):
                    q = x + dx, y + dy
                    if -half <= q[0] <= half and -half <= q[1] <= half:
                        required.add(q)
        required.discard(anchor)
        fresh = required - set(observed)
        if len(observed) + len(fresh) > budget:
            blocked.add(cell)
            continue
        read(required, risk(cell)[1])
        leaves.remove(cell)
        leaves.extend(children)

    # 将自适应叶子重建到公共基础栅格。共享边上强制使用同一组实测结点，
    # 通过分段线性边界和Coons补片消除粗细单元之间的接缝；内部实测覆盖估值。
    def edge(a, b, p):
        nodes = sorted([a, b] + [q for q, v in observed.items() if v is not None and
            ((a[0] == b[0] == q[0] and min(a[1], b[1]) < q[1] < max(a[1], b[1])) or
             (a[1] == b[1] == q[1] and min(a[0], b[0]) < q[0] < max(a[0], b[0])))])
        dim = 1 if a[0] == b[0] else 0
        nodes.sort(key=lambda q: q[dim])
        for left, right in zip(nodes, nodes[1:]):
            if left[dim] <= p[dim] <= right[dim]:
                va, vb = value(left), value(right)
                if va is None or vb is None:
                    return None
                u = (p[dim] - left[dim]) / (right[dim] - left[dim])
                return va * (1 - u) + vb * u
        return None

    prediction, unresolved = {}, set()
    for cell in leaves:
        x0, y0, x1, y1 = cell
        vals = [value(p) for p in corners(cell)]
        if any(v is None for v in vals):
            continue
        all_positions = {(x, y) for x in range(x0, x1 + 1, spacing) for y in range(y0, y1 + 1, spacing)}
        is_unresolved = bool(risk(cell)[0] and (all_positions - set(observed) - {anchor}))
        for x in range(x0, x1 + 1, spacing):
            for y in range(y0, y1 + 1, spacing):
                s, t = (x - x0) / (x1 - x0), (y - y0) / (y1 - y0)
                bottom = edge((x0, y0), (x1, y0), (x, y0))
                top = edge((x0, y1), (x1, y1), (x, y1))
                left = edge((x0, y0), (x0, y1), (x0, y))
                right = edge((x1, y0), (x1, y1), (x1, y))
                if any(v is None for v in (bottom, top, left, right)):
                    continue
                bilinear = vals[0]*(1-s)*(1-t) + vals[1]*s*(1-t) + vals[2]*s*t + vals[3]*(1-s)*t
                available = vals + [v for p,v in observed.items() if v is not None and
                                     x0 <= p[0] <= x1 and y0 <= p[1] <= y1]
                estimate = bottom*(1-t) + top*t + left*(1-s) + right*s - bilinear
                # 边界插值可能在内部过冲，不允许产生低于/高于该单元全部已测值的新极值。
                prediction[x, y] = max(min(available), min(max(available), estimate))
                if is_unresolved:
                    unresolved.add((x, y))
    prediction.update({p: v for p, v in observed.items() if v is not None})
    for p, v in observed.items():
        if v is None:
            prediction.pop(p, None)
    prediction[anchor] = 0.0
    return {'observed': observed, 'prediction': prediction, 'leaves': leaves,
            'unresolved': unresolved, 'phases': phases, 'queryCount': len(observed),
            'budgetExhausted': bool(blocked or (len(observed) >= budget and unresolved)),
            'halfM': half, 'spacingM': spacing}
