"""离线准确性审计：只读历史测值，零网络，不生成产品 live 缓存。"""
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from shapely.geometry import Point
from shapely import union_all
from shapely.geometry import Polygon
from core.coord import dest_at
from core.isochrone import compute_isochrone_batched, ALGORITHM_VERSION
from core.route_band import route_centers, union_circles


def main():
    root = Path(__file__).resolve().parents[2]
    cache = root / 'experiments/logs/cache.db'
    ledger = root / 'experiments/logs/calls.db'
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [cache, ledger]}
    rows = []
    with sqlite3.connect(f'file:{cache}?mode=ro', uri=True) as db:
        for name in ['huilongguan', 'chengdu', 'shanghai']:
            source = root / f'experiments/results/e10_boundary/e10x_{name}.json'
            data = json.loads(source.read_text())
            lat, lng = data['center']
            values = {(a, b): t for a, b, t in db.execute('SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=? AND mode=?', (round(lat, 6), round(lng, 6), 'walking'))}
            used = set()
            def measure(points):
                keys = [tuple(round(v, 6) for v in dest_at(lng, lat, bearing, radius)) for bearing, radius in points]
                used.update(keys)
                return [values.get(key) for key in keys]
            iso = compute_isochrone_batched(measure, threshold_s=900, max_pairs=64)
            result = {'sample': data['city'], 'historicalSource': str(source.relative_to(root)),
                      'status': iso.status, 'probes': iso.pairs_used, 'missingBearings': iso.failed_bearings,
                      'algorithmVersion': ALGORITHM_VERSION}
            if iso.status == 'complete':
                circles = union_circles([{**iso.as_dict(), 'origin': {'lng': lng, 'lat': lat}}])
                shape = union_all([Polygon([(p['lng'], p['lat']) for p in ring]) for ring in circles['fills']])
                held = sorted((key, time) for key, time in values.items() if key not in used and time is not None and math.isfinite(time) and time >= 0)
                held = held[::max(1, math.ceil(len(held) / 200))]
                tp = fp = fn = tn = 0
                for (a, b), time in held:
                    predicted, truth = shape.covers(Point(b, a)), time <= 900
                    if predicted and truth: tp += 1
                    elif predicted: fp += 1
                    elif truth: fn += 1
                    else: tn += 1
                result.update({'heldOutCachedPoints': len(held), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                               'sampledIoU': round(tp / (tp + fp + fn), 4) if tp + fp + fn else None})
            rows.append(result)
            # 单独的八向形状消融；历史加密边界的半径不能冒充当前算法重算成功。
            historical = {float(b): r for b, r in data.get('radii', {}).items()}
            eight = {str(b): historical[b] for b in range(0, 360, 45) if b in historical}
            if len(eight) == 8:
                rings = union_circles([{'status': 'complete', 'origin': {'lng': lng, 'lat': lat}, 'radiiM': eight}])
                polygon = union_all([Polygon([(p['lng'], p['lat']) for p in ring]) for ring in rings['fills']])
                held = []
                for (a, b), time in sorted(values.items()):
                    angle = math.degrees(math.atan2((b - lng) * math.cos(math.radians(lat)), a - lat)) % 360
                    if min(angle % 45, 45 - angle % 45) < 1 or time is None or not math.isfinite(time) or time < 0:
                        continue
                    held.append(((a, b), time))
                held = held[::max(1, math.ceil(len(held) / 200))]
                tp = fp = fn = tn = 0
                for (a, b), time in held:
                    predicted, truth = polygon.covers(Point(b, a)), time <= 900
                    if predicted and truth: tp += 1
                    elif predicted: fp += 1
                    elif truth: fn += 1
                    else: tn += 1
                result['historicalEightDirectionAblation'] = {'note': '历史加密边界只保留八向的形状消融，非当前算法精度',
                    'cachedNonRayPoints': len(held), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                    'sampledIoU': round(tp / (tp + fp + fn), 4) if tp + fp + fn else None}
    long_route = [{'lng': 116.3 + i * .001, 'lat': 40, 'crs': 'BD09'} for i in range(201)]
    sampling = route_centers(long_route)
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [cache, ledger]}
    assert before == after
    output = {'sourceKind': 'historical-readonly-audit', 'liveRequests': 0, 'livePairs': 0,
              'note': '历史非均匀缓存留出点，不是新 live 验收或连续路网全量精度；缺探针不插值补真值。',
              'samples': rows, 'longRoute': {'centers': len(sampling['centers']), 'distanceM': sampling['distanceM'],
                                            'maxGapM': sampling['maxGapM'], 'reversedCentersSame': route_centers(list(reversed(long_route)))['centers'] == list(reversed(sampling['centers']))},
              'historicalFilesUnchanged': before == after, 'sourceHashes': before}
    (root / 'docs/acceptance-cached-accuracy.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
