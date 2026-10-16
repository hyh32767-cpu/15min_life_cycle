"""Quota/auth/network handling without network or production cache writes."""
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from api.app.config import Settings
from api.app.services.baidu_service import BaiduService
from api.app.services.errors import ServiceError
from core.baidu_client import ApiResult, product_context, get
from core.ratelimit import AdaptiveRateLimiter, TokenBucket


def service(tmp_path):
    settings = Settings(baidu_ak="test", baidu_sk="", request_timeout_s=1,
                        cache_db=str(tmp_path / "cache.db"), ledger_db=str(tmp_path / "ledger.db"))
    return BaiduService(settings, adapter=object(), rate_limiter=AdaptiveRateLimiter(base_qps=0))


def resolve(svc, call, marker=1):
    return svc._resolve(trace_id="test", stage="test", interface="test", interface_version="v1",
                        params={"marker": marker}, invoke=call)


@pytest.mark.parametrize("status,code", [(302, "QUOTA_EXCEEDED"), (211, "UPSTREAM_AUTH"), (240, "UPSTREAM_AUTH")])
def test_permanent_errors_do_not_retry_and_block_uncached_requests(tmp_path, status, code):
    svc = service(tmp_path)
    calls = []
    def call():
        calls.append(1)
        return ApiResult(False, status, "secret upstream URL must not reach user")
    for marker in [1, 2]:
        with pytest.raises(ServiceError) as error:
            resolve(svc, call, marker)
        assert error.value.code == code
        assert "secret" not in error.value.message
        assert error.value.retry_after > 0
    assert len(calls) == 1


def test_valid_cache_remains_available_during_quota_cooldown(tmp_path):
    svc = service(tmp_path)
    resolve(svc, lambda: ApiResult(True, 0, "", {"value": 42}))
    with pytest.raises(ServiceError):
        resolve(svc, lambda: ApiResult(False, 302, ""), 2)
    result = resolve(svc, lambda: pytest.fail("Fresh cached data should not invoke upstream"))
    assert result.body == {"value": 42} and result.cache_hit


def test_transient_retries_are_bounded_and_each_attempt_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr("api.app.services.baidu_service.time.sleep", lambda _: None)
    svc = service(tmp_path)
    calls = []
    def call():
        calls.append(1)
        return ApiResult(False, -3, "timeout")
    with pytest.raises(ServiceError) as error:
        resolve(svc, call)
    assert error.value.code == "UPSTREAM_TIMEOUT" and error.value.retryable
    assert len(calls) == svc.rate_limiter.acquired_count == 3
    assert svc.ledger.summary().live_requests == 3


def test_bad_json_is_typed_and_never_retried_in_transport(monkeypatch):
    monkeypatch.setattr("core.baidu_client.urllib.request.urlopen", lambda *a, **k: io.BytesIO(b"<html>unavailable</html>"))
    with product_context("test"):
        result = get("/test", {}, kind="test", experiment_id="test")
    assert result.status == -2 and result.failure_kind == "invalid_response"
    assert result.attempts == 1


def test_singleflight_failure_is_shared_without_duplicate_requests(tmp_path):
    svc = service(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def call():
        entered.set()
        assert release.wait(3)
        return ApiResult(False, 302, "quota")
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(resolve, svc, call)
        assert entered.wait(2)
        second = pool.submit(resolve, svc, call)
        # Wait until the second caller has joined the flight.
        import time
        deadline = time.monotonic() + 2
        while not svc._singleflight.coalesced_count and time.monotonic() < deadline:
            time.sleep(.001)
        release.set()
        for future in (first, second):
            with pytest.raises(ServiceError):
                future.result()
    assert svc.ledger.summary().live_requests == 1


def test_token_bucket_wait_is_bounded():
    bucket = TokenBucket(0.1, 1)
    bucket.acquire()
    with pytest.raises(TimeoutError):
        bucket.acquire(max_wait_s=.01)
    with pytest.raises(ValueError):
        bucket.acquire(2)


def test_product_direct_transport_only_overrides_proxy_handler(monkeypatch):
    from types import SimpleNamespace
    from core import baidu_client as bc
    handlers = []
    def build(*args):
        handlers.extend(args)
        return SimpleNamespace(open=lambda *a, **k: io.BytesIO(b'{"status":0,"result":[]}'))
    monkeypatch.setenv('BAIDU_HTTP_TRANSPORT', 'direct')
    monkeypatch.setattr(bc.urllib.request, 'build_opener', build)
    monkeypatch.setattr(bc.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('direct uses explicit opener'))
    with bc.product_context('fake'):
        result = bc.get('/routematrix/v2/walking', {}, kind='matrix_walking', experiment_id='test')
    assert result.status == 0
    assert len(handlers) == 1
    assert isinstance(handlers[0], bc.urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}


def test_request_queued_before_cooldown_does_not_invoke_upstream(tmp_path):
    import time
    svc = service(tmp_path)
    class Queue:
        def acquire(self, cost):
            svc._cooldowns['test'] = (time.monotonic() + 15,
                ServiceError('RATE_LIMITED', '冷却中', retryable=True, retry_after=15))
    svc._interface_limits['test'] = Queue()
    with pytest.raises(ServiceError) as error:
        resolve(svc, lambda: pytest.fail('A cooldown began while this request was queued'))
    assert error.value.code == 'RATE_LIMITED'


@pytest.mark.parametrize("item", [{}, {"duration": {}}, {"duration": {"value": 0}, "distance": {"value": 0}}])
def test_missing_matrix_time_is_unknown_not_instantly_reachable_or_no_route(item):
    cell = BaiduService._matrix_cell(0, 0, item, "live-api")
    assert cell["status"] == "error"
    assert cell["durationSeconds"] is None


def test_explicit_no_route_is_distinct_from_missing_matrix_fields():
    assert BaiduService._matrix_cell(0, 0, {"status": 2001}, "live-api")["status"] == "no_route"
