# -*- coding: utf-8 -*-
"""QPS 令牌桶限流、自适应退避(AIMD)与并发单飞(Singleflight)合并。

源自 E0.3 / E3 并发标定实验结论（docs/01、docs/11）：
- 百度地图开放平台步行算路/批量矩阵安全匀速线为 8~10 QPS；
- 遇到 401 并发限流时采用乘性减半(MD)与抖动退避，成功响应后线性恢复(AI)；
- 相同 request_hash 的并发请求通过 Singleflight 合并，避免瞬时击穿缓存与配额。
"""
from __future__ import annotations

import random
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from collections import deque


class WindowRateLimiter:
    """按成本控制滑动时间窗用量；矩阵成本为 OD 条数，而不是 HTTP 次数。"""
    def __init__(self, capacity: int, *, window_s=1.05, clock=time.monotonic, sleeper=time.sleep):
        if not math.isfinite(window_s) or window_s <= 0:
            raise ValueError('window_s must be finite and positive')
        self.capacity = max(1, capacity)
        self.window_s = float(window_s)
        self._base_window_s = self.window_s
        self._successes = 0
        self._clock, self._sleep = clock, sleeper
        self._lock = threading.Lock()
        self._events = deque()

    def on_rate_limited(self) -> None:
        """保持单批容量，延长真实成本窗口，不能只降低HTTP频率。"""
        with self._lock:
            self.window_s = min(60.0, self.window_s * 2)
            self._successes = 0

    def on_success(self) -> None:
        with self._lock:
            if self.window_s <= self._base_window_s:
                return
            self._successes += 1
            if self._successes >= 10:
                self.window_s = max(self._base_window_s, self.window_s * .9)
                self._successes = 0

    def acquire(self, cost: int = 1, max_wait_s: float = 10.0) -> float:
        if cost < 1 or cost > self.capacity:
            raise ValueError("request cost exceeds window capacity")
        start = self._clock()
        while True:
            with self._lock:
                now = self._clock()
                while self._events and now - self._events[0][0] >= self.window_s:
                    self._events.popleft()
                if sum(n for _, n in self._events) + cost <= self.capacity:
                    self._events.append((now, cost))
                    return now - start
                delay = max(0.001, self.window_s - (now - self._events[0][0]))
            if self._clock() + delay - start > max_wait_s:
                raise TimeoutError("quota queue timeout")
            self._sleep(delay)


class TokenBucket:
    """线程安全令牌桶限流器。rate_qps <= 0 时不限速（用于离线单测）。"""

    def __init__(self, rate_qps: float = 10.0, burst: int = 10,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleeper
        if not math.isfinite(float(rate_qps)):
            raise ValueError("rate_qps must be finite")
        self._rate = max(0.0, float(rate_qps))
        self._burst = max(1.0, float(burst))
        self._tokens = self._burst
        self._last = self._clock()

    @property
    def rate_qps(self) -> float:
        with self._lock:
            return self._rate

    def set_rate(self, rate_qps: float) -> None:
        if not math.isfinite(rate_qps):
            raise ValueError("rate_qps must be finite")
        with self._lock:
            self._refill_locked()
            self._rate = max(0.0, float(rate_qps))

    def _refill_locked(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        if self._rate > 0:
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

    def acquire(self, tokens: float = 1.0, max_wait_s: float = 10.0) -> float:
        """获取令牌，返回实际等待秒数。"""
        if not math.isfinite(tokens) or not math.isfinite(max_wait_s) or max_wait_s < 0:
            raise ValueError("tokens and wait must be finite")
        if tokens <= 0:
            return 0.0
        if self._rate > 0 and tokens > self._burst:
            raise ValueError("tokens exceed bucket capacity")
        waited = 0.0
        deadline = self._clock() + max_wait_s
        while True:
            with self._lock:
                if self._rate <= 0:
                    return 0.0
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                wait_s = deficit / self._rate
            if wait_s > 0:
                if self._clock() + wait_s > deadline:
                    raise TimeoutError("rate limiter queue timeout")
                self._sleep(wait_s)
                waited += wait_s


@dataclass
class RateLimiterStats:
    base_qps: float
    current_qps: float
    acquired_count: int
    throttled_count: int
    rate_limited_count: int
    coalesced_count: int


class AdaptiveRateLimiter:
    """AIMD 自适应 QPS 控制器：正常时按令牌桶匀速放行，遇 401 自动降速退避。"""

    def __init__(self, base_qps: float = 10.0, min_qps: float = 1.0,
                 burst: int = 10,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep) -> None:
        self.base_qps = max(0.0, float(base_qps))
        self.min_qps = max(0.5, float(min_qps))
        self._current_qps = self.base_qps
        self._bucket = TokenBucket(rate_qps=self.base_qps, burst=burst,
                                   clock=clock, sleeper=sleeper)
        self._sleep = sleeper
        self._lock = threading.Lock()
        self.acquired_count = 0
        self.throttled_count = 0
        self.rate_limited_count = 0

    @property
    def current_qps(self) -> float:
        with self._lock:
            return self._current_qps

    def acquire(self, tokens: float = 1.0) -> float:
        waited = self._bucket.acquire(tokens)
        with self._lock:
            self.acquired_count += 1
            if waited > 0.001:
                self.throttled_count += 1
        return waited

    def on_rate_limited(self, attempt: int = 0, *,
                        base_Wait_s: Optional[float] = None) -> float:
        """遇到 401 并发限流时乘性降速，并计算退避等待秒数。"""
        with self._lock:
            self.rate_limited_count += 1
            if self._current_qps > 0:
                self._current_qps = max(self.min_qps, self._current_qps * 0.5)
                self._bucket.set_rate(self._current_qps)
        if base_Wait_s is not None:
            delay = base_Wait_s
        else:
            delay = min(2.0, 0.4 * 2 ** attempt) + random.uniform(0, 0.15)
        self._sleep(delay)
        return delay

    def on_success(self) -> None:
        """成功响应后加性恢复 QPS 至 base_qps。"""
        with self._lock:
            if 0 < self._current_qps < self.base_qps:
                self._current_qps = min(self.base_qps, self._current_qps + 0.5)
                self._bucket.set_rate(self._current_qps)


class _CallState:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: Optional[BaseException] = None


class Singleflight:
    """相同请求 key 并发合并器：同一时刻只允许一个线程执行上游请求，其余等待复用结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: Dict[str, _CallState] = {}
        self.coalesced_count = 0

    def do(self, key: str, fn: Callable[[], Any], timeout_s: float = 45.0) -> Tuple[Any, bool]:
        """执行或等待相同 key 的调用，返回 (result, shared)。"""
        with self._lock:
            existing = self._in_flight.get(key)
            if existing is not None:
                self.coalesced_count += 1
                state = existing
                leader = False
            else:
                state = _CallState()
                self._in_flight[key] = state
                leader = True

        if not leader:
            if not state.event.wait(timeout_s):
                raise TimeoutError("singleflight wait timeout")
            if state.error is not None:
                raise state.error
            return state.result, True

        try:
            state.result = fn()
            return state.result, False
        except BaseException as exc:
            state.error = exc
            raise
        finally:
            with self._lock:
                self._in_flight.pop(key, None)
            state.event.set()
