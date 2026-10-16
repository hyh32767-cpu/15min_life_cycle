"""受限真实测试：矩阵发送间隔二分或指定批量连续验证。仅服务器手动运行。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import pwd
import sqlite3
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    parser.add_argument('--max-requests', type=int, default=60)
    parser.add_argument('--pairs-per-request', type=int, default=50)
    parser.add_argument('--fixed-interval', type=float)
    parser.add_argument('--confirmation-requests', type=int, default=18)
    parser.add_argument('--interval-step', type=float, default=.5)
    parser.add_argument('--output-name', default='matrix-envelope-20261016.json')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('真实请求需显式传入--run-live')
    if not 1 <= args.max_requests <= 80:
        parser.error('max-requests必须为1至80')
    if not 1 <= args.pairs_per_request <= 50:
        parser.error('pairs-per-request必须为1至50')
    if args.fixed_interval is not None and not 0.1 <= args.fixed_interval <= 60:
        parser.error('fixed-interval必须为0.1至60秒')
    if not 12 <= args.confirmation_requests <= 80:
        parser.error('confirmation-requests必须为12至80')
    if not math.isfinite(args.interval_step) or not .05 <= args.interval_step <= 5:
        parser.error('interval-step必须为0.05至5秒')
    if Path(args.output_name).name != args.output_name:
        parser.error('output-name只能为文件名')
    pairs = args.pairs_per_request
    cfg = {}
    for line in Path('/etc/shunshou.env').read_text().splitlines():
        k, sep, v = line.partition('=')
        if sep and not k.lstrip().startswith('#'):
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    os.environ.update(cfg)
    os.environ['BAIDU_HTTP_TRANSPORT'] = 'direct'
    os.environ['LEDGER_DB'] = '/var/lib/shunshou/ledger.db'
    os.chdir('/opt/shunshou/current')
    sys.path.insert(0, str(Path.cwd()))
    account = pwd.getpwnam('shunshou')
    os.setgroups([])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    from api.app.adapters.baidu.client import BaiduAdapter
    from api.app.storage.api_cache import ApiCache, request_hash, response_hash
    from api.app.storage.ledger import ProductLedger
    from core.coord import dest_at

    cache = ApiCache('/var/lib/shunshou/cache.db')
    ledger = ProductLedger('/var/lib/shunshou/ledger.db')
    adapter = BaiduAdapter(10, cfg['BAIDU_MAP_AK'], cfg.get('BAIDU_MAP_SK', ''))
    trace = uuid.uuid4().hex[:16]
    origin = (39.915062, 116.417939)
    output = Path('/var/lib/shunshou') / args.output_name
    begin = time.monotonic()
    report = {'startedAt': datetime.now(timezone.utc).isoformat(), 'traceId': trace,
              'maxRequests': args.max_requests, 'maxAttemptPairs': pairs * args.max_requests,
              'pairsPerRequest': pairs, 'stages': [], 'status': 'running',
              'retries': 0, 'cacheHits': 0, 'productionConfigChanged': False}
    requests_used = 0
    candidate_index = 0
    last_start = None
    last_failed = False

    def emit(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    def save():
        report.update(requestsUsed=requests_used, attemptPairs=requests_used * pairs,
                      elapsedSeconds=round(time.monotonic() - begin, 3))
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        output.chmod(0o600)

    def pause_until(deadline):
        while time.monotonic() < deadline:
            time.sleep(min(5, deadline - time.monotonic()))

    def stage(interval, count, kind):
        nonlocal requests_used, candidate_index, last_start, last_failed
        if last_failed:
            emit({'event': 'cooldown', 'seconds': 65})
            pause_until(time.monotonic() + 65)
        record = {'intervalSeconds': interval, 'plannedRequests': count,
                  'kind': kind, 'requests': [], 'passed': False}
        report['stages'].append(record)
        emit({'event': 'stage-start', 'intervalSeconds': interval,
              'count': count, 'kind': kind})
        for index in range(count):
            if requests_used >= args.max_requests:
                raise RuntimeError('probe_budget_exhausted')
            destinations = []
            while len(destinations) < pairs:
                candidates = []
                for _ in range(pairs - len(destinations)):
                    i = candidate_index
                    candidate_index += 1
                    candidates.append(dest_at(origin[1], origin[0],
                        (i * 137.507764 + 61.396 + pairs * .371) % 360, 380 + i * .139))
                found = cache.matrix_cells([list(origin)], [list(p) for p in candidates])
                destinations.extend(p for j, p in enumerate(candidates) if (0, j) not in found)
            if last_start is not None:
                pause_until(last_start + interval)
            sent = last_start = time.monotonic()
            result = adapter.routematrix([origin], destinations, experiment_id=trace)
            ended = time.monotonic()
            requests_used += 1
            valid = sum(isinstance(item.get('duration'), dict)
                        and isinstance(item['duration'].get('value'), (int, float))
                        and math.isfinite(item['duration']['value'])
                        and item['duration']['value'] > 0
                        for item in result.data.get('result', [])) if result.ok else 0
            params = {'origins': [list(origin)], 'destinations': [list(p) for p in destinations],
                      'mode': 'walking'}
            ledger.record(trace_id=trace, stage='matrix-envelope-20261016',
                interface='matrix_walking', request_hash=request_hash('matrix_walking', 'v2', 'BD09', params),
                cache_hit=False, status=result.status, requests=1, pairs=pairs,
                latency_ms=result.latency_ms, response_hash=response_hash(result.data),
                message=f'controlled {pairs}-pair envelope probe interval={interval}')
            if result.ok:
                cache.put(interface='matrix_walking', interface_version='v2', crs='BD09',
                    params=params, body=result.data, status=0, latency_ms=result.latency_ms, ttl_s=21600)
            row = {'index': index + 1, 'status': result.status, 'validPairs': valid,
                   'latencyMs': result.latency_ms, 'sentSeconds': round(sent - begin, 3),
                   'endedSeconds': round(ended - begin, 3)}
            record['requests'].append(row)
            last_failed = result.status == 401
            emit({'event': 'request', 'intervalSeconds': interval, 'kind': kind, **row})
            save()
            if result.status == 401:
                emit({'event': 'stage-failed', 'intervalSeconds': interval, 'afterRequests': index + 1})
                return False
            if result.status != 0 or valid != pairs:
                raise RuntimeError('non_rate_error_or_incomplete_response')
        record['passed'] = True
        save()
        emit({'event': 'stage-passed', 'intervalSeconds': interval, 'count': count})
        return True

    emit({'event': 'start', 'traceId': trace, 'maxRequests': args.max_requests,
          'pairsPerRequest': pairs, 'fixedIntervalSeconds': args.fixed_interval,
          'shortStageRequests': 6,
          'confirmationRequests': args.confirmation_requests if args.fixed_interval is not None else 12,
          'resolutionSeconds': args.interval_step if args.fixed_interval is not None else 1})
    try:
        if args.fixed_interval is not None:
            # 不同实验进程衔接时不额外制造一对紧挨着的批次。
            with sqlite3.connect('file:/var/lib/shunshou/ledger.db?mode=ro', uri=True) as conn:
                previous = conn.execute("SELECT created_at FROM api_calls WHERE "
                    "stage='matrix-envelope-20261016' AND cache_hit=0 ORDER BY id DESC LIMIT 1").fetchone()
            if previous:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous[0])).total_seconds()
                delay = max(0, 10 - age)
                if delay:
                    emit({'event': 'inter-stage-gap', 'seconds': round(delay, 3)})
                    pause_until(time.monotonic() + delay)
            interval = args.fixed_interval
            while not stage(interval, args.confirmation_requests, 'fixed-confirmation'):
                report['failedIntervalSeconds'] = interval
                interval = round(interval + args.interval_step, 3)
                if interval > 60:
                    raise RuntimeError('no_pass_within_60_second_interval')
            report.update(status='complete', confirmedIntervalSeconds=interval,
                          confirmationRequests=args.confirmation_requests)
            return
        low, high = 6, 18
        while not stage(high, 6, 'establish-upper'):
            low, high = high, high + 6
            if high > 60:
                raise RuntimeError('no_pass_within_60_second_interval')
        while True:
            while high - low > 1:
                middle = (high + low) // 2
                if stage(middle, 6, 'binary-search'):
                    high = middle
                else:
                    low = middle
            report.update(failedIntervalSeconds=low, candidateIntervalSeconds=high)
            save()
            if stage(high, 12, 'confirmation'):
                report.update(status='complete', confirmedIntervalSeconds=high,
                              confirmationRequests=12, failedIntervalSeconds=low)
                break
            low = high
            high += 1
            while not stage(high, 6, 'backoff'):
                low, high = high, high + 1
                if high > 60:
                    raise RuntimeError('no_pass_within_60_second_interval')
    except Exception as exc:
        report.update(status='stopped', stopReason=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
    finally:
        save()
        emit({'event': 'finished', **{k: v for k, v in report.items() if k != 'stages'}})


if __name__ == '__main__':
    main()
