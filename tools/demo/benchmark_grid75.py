"""指定1.1km方形内75m网格冷启动测速；显式授权运行，不修改生产配置。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import time

from tools.demo.benchmark_video_isochrone import SerialMatrixPacer

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    if not parser.parse_args().run_live:
        parser.error('真实调用必须显式传--run-live')
    cfg = {}
    for line in (ROOT / '.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.lstrip().startswith('#'):
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    if not cfg.get('BAIDU_MAP_AK'):
        raise SystemExit('缺少BAIDU_MAP_AK')
    os.environ.update(BAIDU_MAP_AK=cfg['BAIDU_MAP_AK'],
                      BAIDU_MAP_SK=cfg.get('BAIDU_MAP_SK', ''),
                      BAIDU_HTTP_TRANSPORT='direct',
                      BAIDU_MATRIX_ROUTES_PER_WINDOW='50',
                      BAIDU_MATRIX_WINDOW_SECONDS='4.2')
    directory = ROOT / 'output/benchmarks' / ('grid75-square1100-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    directory.mkdir(parents=True)
    os.environ['LEDGER_DB'] = str(directory / 'ledger.db')
    from api.app.config import Settings
    from api.app.models.common import Coord
    from api.app.services.baidu_service import BaiduService
    settings = Settings(baidu_ak=cfg['BAIDU_MAP_AK'], baidu_sk=cfg.get('BAIDU_MAP_SK', ''),
        cache_db=str(directory / 'cache.db'), ledger_db=str(directory / 'ledger.db'),
        derived_db=str(directory / 'derived.db'), request_timeout_s=10)
    service = BaiduService(settings)
    pacer = SerialMatrixPacer()
    service._interface_limits['matrix_walking'] = pacer
    service._matrix_parallel = False
    origin = Coord(lng=116.417939, lat=39.915062, crs='BD09')
    points = [{'eastM': east, 'northM': north,
               'coord': {'lng': origin.lng + east / (111320 * math.cos(math.radians(origin.lat))),
                         'lat': origin.lat + north / 111320, 'crs': 'BD09'}}
              for north in range(-525, 526, 75) for east in range(-525, 526, 75)]
    assert len(points) == 225
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    batches = []
    for offset in range(0, len(points), 50):
        batch = points[offset:offset + 50]
        batch_start = time.monotonic()
        try:
            result = service.travel_matrix([origin], [Coord(**p['coord']) for p in batch],
                trace_id='grid75-square1100', stage='grid75-benchmark')
            cells = result['cells']
            for point, cell in zip(batch, cells):
                point['measurement'] = cell
            event = {'batch': len(batches) + 1, 'pairs': len(batch),
                     'valid': sum(c['status'] == 'ok' for c in cells)}
        except Exception as exc:
            # 不输出可能包含带密钥URL的异常文本。
            event = {'batch': len(batches) + 1, 'pairs': len(batch),
                     'errorType': type(exc).__name__, 'errorCode': getattr(exc, 'code', None)}
        event.update(elapsedSeconds=round(time.monotonic() - start, 3),
                     batchSeconds=round(time.monotonic() - batch_start, 3))
        batches.append(event)
        print(json.dumps(event), flush=True)
        if 'errorType' in event:
            break
    elapsed = round(time.monotonic() - start, 3)
    with sqlite3.connect(settings.ledger_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute('SELECT * FROM api_calls ORDER BY id')]
    live = [r for r in rows if not r['cache_hit']]
    valid = [p for p in points if p.get('measurement', {}).get('status') == 'ok']
    summary = {'startedAt': started_at, 'elapsedSeconds': elapsed,
        'gridPoints': len(points), 'validPoints': len(valid), 'unknownPoints': len(points) - len(valid),
        'reachableWithin900s': sum(p['measurement']['durationSeconds'] <= 900 for p in valid),
        'liveRequests': sum(r['requests'] for r in live),
        'attemptPairs': sum(r['pairs'] for r in live),
        'rateLimitedRequests': sum(r['requests'] for r in live if r['status'] == 401),
        'cachePairs': sum(r['pairs'] for r in rows if r['cache_hit']),
        'networkResponseSeconds': round(sum(r['latency_ms'] for r in live) / 1000, 3),
        'pacingWaitSeconds': round(sum(e['waitSeconds'] for e in pacer.events), 3),
        'isolatedEmptyCacheAtStart': True, 'productionConfigChanged': False}
    report = {'summary': summary, 'origin': origin.model_dump(),
        'grid': {'squareSideM': 1100, 'spacingM': 75, 'offsetMinM': -525, 'offsetMaxM': 525,
                 'edgeMarginM': 25, 'rows': 15, 'columns': 15,
                 'note': '指定方形窗口，不代表完整15分钟等时圈；中心零耗时未当作API有效测值'},
        'strategy': {'parallelRequests': 1, 'batchPairs': 50, 'fullBatchStartIntervalSeconds': 9},
        'batches': batches, 'points': points, 'ledger': rows,
        'pacingEvents': [{k: v for k, v in e.items() if k != 'sentMonotonic'} for e in pacer.events]}
    path = directory / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'event': 'finished', **summary, 'reportFile': str(path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
