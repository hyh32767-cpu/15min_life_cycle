"""单次固定网格实验：复用正式HTTP接口、缓存及限流，不修改生产算法。"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:18080')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # 与视频/固定16向实验共用公开中心，均为BD09。仅本次固定规模。
    origin = {'lng': 116.417939, 'lat': 39.915062, 'crs': 'BD09'}
    spacing, radius = 200, 1400
    points = []
    for north in range(-radius, radius + 1, spacing):
        for east in range(-radius, radius + 1, spacing):
            distance = math.hypot(east, north)
            if distance > radius:
                continue
            # 与core.coord.dest_at相同的本地等距圆柱近似。
            lat2 = origin['lat'] + north / 111320.0
            lng2 = origin['lng'] + east / (111320.0 * math.cos(math.radians(origin['lat'])))
            points.append({'eastM': east, 'northM': north,
                           'coord': {'lng': lng2, 'lat': lat2, 'crs': 'BD09'}})
    chunks = [(i, points[i:i + 25]) for i in range(0, len(points), 25)]
    start = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()

    def run_chunk(job):
        index, chunk = job
        submitted = time.monotonic() - start
        payload = {'origins': [origin], 'destinations': [p['coord'] for p in chunk]}
        req = urllib.request.Request(args.base_url + '/api/travel-matrix',
                                     data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        result = {'startIndex': index, 'count': len(chunk), 'submittedSeconds': round(submitted, 3)}
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                result['response'] = json.load(response)
                result['httpStatus'] = response.status
        except urllib.error.HTTPError as exc:
            result.update(httpStatus=exc.code, response=json.loads(exc.read()))
        except (urllib.error.URLError, TimeoutError) as exc:
            result.update(errorType=type(exc).__name__)
        result['completedSeconds'] = round(time.monotonic() - start, 3)
        print(json.dumps({'event': 'batch', **{k: v for k, v in result.items() if k != 'response'}}, ensure_ascii=False), flush=True)
        return result

    print(json.dumps({'event': 'start', 'points': len(points), 'spacingM': spacing,
                      'radiusM': radius, 'batches': len(chunks), 'parallelHttpRequests': 2}), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(run_chunk, chunks))
    samples = []
    for batch in batches:
        cells = {c['toIndex']: c for c in batch.get('response', {}).get('cells', [])}
        for j in range(batch['count']):
            cell = cells.get(j, {'status': 'error', 'durationSeconds': None})
            samples.append({**points[batch['startIndex'] + j], **cell})
    summary = {'startedAt': started_at, 'elapsedSeconds': round(time.monotonic() - start, 3),
               'points': len(points), 'spacingM': spacing, 'radiusM': radius, 'thresholdSeconds': 900,
               'statuses': dict(Counter(s['status'] for s in samples)),
               'reachablePoints': sum(s['status'] == 'ok' and s['durationSeconds'] <= 900 for s in samples),
               'cacheCells': sum(s.get('sourceKind') == 'api-cache' for s in samples),
               'traceIds': [b['response']['traceId'] for b in batches if 'traceId' in b.get('response', {})]}
    Path(args.output).write_text(json.dumps({'summary': summary, 'origin': origin,
                                            'samples': samples, 'batches': batches}, ensure_ascii=False, indent=2))
    print(json.dumps({'event': 'finished', **summary}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
