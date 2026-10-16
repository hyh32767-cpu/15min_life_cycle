"""手动冷启动重测视频主圈；仅测试进程注入串行节奏，不改生产服务。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


class SerialMatrixPacer:
    """按上一批真实OD成本安排下一批；间距取已测档位之间的线性插值。"""

    PROFILE = ((0, 0), (10, 1.8), (20, 4.1), (30, 6), (40, 7.2), (50, 9))

    def __init__(self, clock=time.monotonic, sleeper=time.sleep):
        self.clock, self.sleeper = clock, sleeper
        self.last_sent = None
        self.last_cost = 0
        self.factor = 1.0
        self.lock = threading.Lock()
        self.events = []

    @classmethod
    def interval(cls, cost):
        if not 1 <= cost <= 50:
            raise ValueError('matrix batch cost must be 1..50')
        for (a, ta), (b, tb) in zip(cls.PROFILE, cls.PROFILE[1:]):
            if a <= cost <= b:
                value = ta + (tb - ta) * (cost - a) / (b - a)
                return math.ceil((value - 1e-9) * 10) / 10
        raise ValueError('unknown batch cost')

    def acquire(self, cost=1, max_wait_s=10.0):
        self.interval(cost)
        with self.lock:
            now = self.clock()
            delay = max(0, self.last_sent + self.interval(self.last_cost) * self.factor - now) if self.last_sent is not None else 0
            if delay > max_wait_s:
                raise TimeoutError('serial matrix pacing queue timeout')
            if delay:
                self.sleeper(delay)
            self.last_sent, self.last_cost = self.clock(), cost
            self.events.append({'sentMonotonic': self.last_sent, 'pairs': cost,
                                'waitSeconds': round(delay, 6), 'backoffFactor': self.factor})
            return delay

    def on_rate_limited(self):
        with self.lock:
            self.factor = min(4, self.factor * 1.25)

    def on_success(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('真实调用必须显式传--run-live')
    # 文件中的新值优先于可能遗留的旧进程变量，不输出凭据。
    cfg = {}
    for line in (ROOT / '.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and not key.lstrip().startswith('#'):
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    if not cfg.get('BAIDU_MAP_AK'):
        raise SystemExit('本地.env缺少BAIDU_MAP_AK')
    os.environ['BAIDU_MAP_AK'] = cfg['BAIDU_MAP_AK']
    os.environ['BAIDU_MAP_SK'] = cfg.get('BAIDU_MAP_SK', '')
    os.environ['BAIDU_HTTP_TRANSPORT'] = 'direct'
    os.environ['BAIDU_MATRIX_ROUTES_PER_WINDOW'] = '50'
    os.environ['BAIDU_MATRIX_WINDOW_SECONDS'] = '4.2'
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    directory = ROOT / 'output' / 'benchmarks' / ('video-circle-serial-' + stamp)
    directory.mkdir(parents=True)
    os.environ['LEDGER_DB'] = str(directory / 'ledger.db')
    from api.app.config import Settings
    from api.app.models.common import Coord
    from api.app.services.baidu_service import BaiduService
    from api.app.services.isochrone_service import IsochroneService
    from api.app.storage.derived_cache import DerivedCache
    settings = Settings(baidu_ak=cfg['BAIDU_MAP_AK'], baidu_sk=cfg.get('BAIDU_MAP_SK', ''),
        cache_db=str(directory / 'cache.db'), ledger_db=str(directory / 'ledger.db'),
        derived_db=str(directory / 'derived.db'), request_timeout_s=10)
    service = BaiduService(settings)
    pacer = SerialMatrixPacer()
    service._interface_limits['matrix_walking'] = pacer
    service._matrix_parallel = False
    circle = IsochroneService(service, cache=DerivedCache(settings.derived_db))
    request = {'origin': {'lng': 116.417939, 'lat': 39.915062, 'crs': 'BD09'},
               'thresholdSeconds': 900, 'bearings': [i * 22.5 for i in range(16)],
               'loM': 200, 'hiM': 1400, 'initialM': 800, 'tolM': 25,
               'maxPairs': 320, 'adaptive': True, 'l2First': True, 'allowL2Fallback': False}
    start = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    progress = []
    first_base = None
    result = circle.run(Coord(**request['origin']), threshold_seconds=900,
        bearings=request['bearings'], lo_m=200, hi_m=1400, initial_m=800,
        tol_m=25, max_pairs=320, adaptive=True, l2_first=True, allow_l2_fallback=False)
    previous = None
    last_print = start
    while True:
        elapsed = time.monotonic() - start
        state = (result.get('status'), result.get('backgroundStatus'),
                 len(result.get('radiiM', {})), result.get('pairsUsed'))
        if result.get('status') == 'complete' and first_base is None:
            first_base = round(elapsed, 3)
        if state != previous or time.monotonic() - last_print > 20:
            point = {'elapsedSeconds': round(elapsed, 3), 'status': state[0],
                     'backgroundStatus': state[1], 'directions': state[2], 'pairsUsed': state[3]}
            progress.append(point)
            print(json.dumps({'event': 'progress', **point}), flush=True)
            previous, last_print = state, time.monotonic()
        if result.get('backgroundStatus') != 'running':
            break
        time.sleep(.25)
        result = circle.get_task_status(result['taskId'])
    elapsed = round(time.monotonic() - start, 3)
    with sqlite3.connect(settings.ledger_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute('SELECT * FROM api_calls ORDER BY id')]
    live = [r for r in rows if not r['cache_hit']]
    summary = {'startedAt': started_at, 'elapsedSeconds': elapsed,
               'firstCompleteMeasuredBoundarySeconds': first_base,
               'status': result.get('status'), 'backgroundStatus': result.get('backgroundStatus'),
               'directions': len(result.get('radiiM', {})), 'pairsUsed': result.get('pairsUsed'),
               'validSamples': (result.get('reconstruction') or {}).get('sampleCount'),
               'liveRequests': sum(r['requests'] for r in live),
               'attemptPairs': sum(r['pairs'] for r in live),
               'successfulLivePairs': sum(r['pairs'] for r in live if r['status'] == 0),
               'rateLimitedRequests': sum(r['requests'] for r in live if r['status'] == 401),
               'cachePairs': sum(r['pairs'] for r in rows if r['cache_hit']),
               'networkResponseSeconds': round(sum(r['latency_ms'] for r in live) / 1000, 3),
               'warnings': result.get('warnings'), 'source': '.env current AK',
               'signingSkConfigured': bool(cfg.get('BAIDU_MAP_SK')), 'transport': 'direct',
               'isolatedEmptyCacheAtStart': True, 'productionConfigChanged': False}
    events = [{**e, 'sentSeconds': round(e['sentMonotonic'] - start, 6)} for e in pacer.events]
    for e in events:
        e.pop('sentMonotonic')
    report = {'summary': summary, 'request': request, 'result': result,
              'progress': progress, 'ledger': rows, 'pacingEvents': events,
              'strategy': {'parallelRequests': 1, 'maxBatchPairs': 50,
                           'profile': pacer.PROFILE, 'roundingSeconds': .1,
                           'intermediateBatchSizes': 'linear interpolation; experiment only'}}
    path = directory / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'event': 'finished', **summary, 'reportFile': str(path)}, ensure_ascii=False), flush=True)
    circle._workers.shutdown(wait=True)


if __name__ == '__main__':
    main()
