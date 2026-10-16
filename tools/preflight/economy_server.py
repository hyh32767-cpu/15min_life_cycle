"""仅用于人工验收的有限额入口；默认 20 请求/100 对，不改变产品配置。"""
import argparse
import json
import threading
import time
from pathlib import Path

from api.app.services.errors import ServiceError


class AcceptanceBudget:
    def __init__(self, requests=20, pairs=100, output=None, interval_ms=0):
        self.max_requests, self.max_pairs = requests, pairs
        self.output = Path(output) if output else None
        self.lock = threading.Lock()
        self.calls = []
        self.blocked_kinds = set()
        self.interval_s = max(0, interval_ms) / 1000
        self.next_call_at = 0.0

    def install(self):
        from core import baidu_client
        original = baidu_client.get

        def bounded(path, params, **kwargs):
            kind = kwargs['kind']
            pairs = kwargs.get('n_pairs', 1)
            with self.lock:
                if (kind in self.blocked_kinds or len(self.calls) >= self.max_requests
                        or sum(call['pairs'] for call in self.calls) + pairs > self.max_pairs):
                    raise ServiceError('ACCEPTANCE_BUDGET', '本轮测量已达到限定额度，可继续查看已保存结果', http_status=429)
                record = {'kind': kind, 'pairs': pairs, 'status': 'pending'}
                self.calls.append(record)
                self.save()
                call_at = max(time.monotonic(), self.next_call_at)
                self.next_call_at = call_at + self.interval_s
            delay = call_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            # 每次真实 HTTP 只尝试一次；服务层若重试仍须重新取得预算。
            result = original(path, params, **{**kwargs, 'retries': 0})
            with self.lock:
                record['status'] = result.status
                if result.status in (4, 302, 401):
                    self.blocked_kinds.add(kind)
                self.save()
            return result

        baidu_client.get = bounded

    def save(self):
        if self.output:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps({'limits': {'requests': self.max_requests, 'pairs': self.max_pairs},
                'requests': len(self.calls), 'pairs': sum(call['pairs'] for call in self.calls),
                'calls': self.calls, 'blockedKinds': sorted(self.blocked_kinds)}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--requests', type=int, default=20)
    parser.add_argument('--pairs', type=int, default=100)
    parser.add_argument('--interval-ms', type=int, default=0, help='实际业务 HTTP 最小间隔，验收时用于避免连续突发请求')
    parser.add_argument('--output', default='docs/acceptance-economy-budget.json')
    parser.add_argument('--resume', action='store_true', help='保留同一轮已用额度，不能靠重启重置')
    parser.add_argument('--retry-rate-limited', action='store_true', help='冷却后仅解锁 401 接口，不解锁配额错误或增加预算')
    args = parser.parse_args()
    budget = AcceptanceBudget(args.requests, args.pairs, args.output, args.interval_ms)
    if args.resume and Path(args.output).exists():
        previous = json.loads(Path(args.output).read_text())
        budget.calls = previous['calls']
        budget.blocked_kinds = set(previous.get('blockedKinds', []))
        if args.retry_rate_limited:
            for kind in list(budget.blocked_kinds):
                last = next(call for call in reversed(budget.calls) if call['kind'] == kind)
                if last['status'] == 401:
                    budget.blocked_kinds.remove(kind)
    budget.save()
    budget.install()
    import uvicorn
    from api.app.main import app
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
