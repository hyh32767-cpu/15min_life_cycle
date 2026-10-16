"""产品调用不得串用凭据或写入历史实验账本。"""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import urllib.error

from core import baidu_client as bc
from api.app.adapters.baidu.client import BaiduAdapter


def test_concurrent_credentials_and_research_ledger_isolation(monkeypatch):
    barrier = Barrier(2)
    def geocode(address, **kwargs):
        barrier.wait(timeout=5)
        bc._record_call(kind="geocode")
        return bc._signed_params("/geocoding/v3/", {})["ak"]
    def forbidden(**kwargs):
        raise AssertionError("产品请求写入了研究账本")
    monkeypatch.setattr(bc, "geocode", geocode)
    monkeypatch.setattr(bc, "log_call", forbidden)
    original = (bc.AK, bc.SK)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(BaiduAdapter(app_key=key).geocode, "测试")
                   for key in ("test-one", "test-two")]
        assert [future.result() for future in futures] == ["test-one", "test-two"]
    assert (bc.AK, bc.SK) == original
    assert bc._product_credentials.get() is None


def test_retry_count_and_context_restoration(monkeypatch):
    calls = []
    def urlopen(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("temporary")
        return io.BytesIO(b'{"status":0,"result":{"location":{"lat":40,"lng":116}}}')
    monkeypatch.setattr(bc.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(bc.time, "sleep", lambda _: None)
    monkeypatch.setattr(bc, "log_call", lambda **kwargs: (_ for _ in ()).throw(AssertionError("research write")))
    result = BaiduAdapter(app_key="test-only").geocode("测试")
    assert not result.ok and result.attempts == 1
    assert len(calls) == 1  # 产品重试统一交给服务层，避免绕过QPS限制
    assert bc._product_credentials.get() is None
    try:
        with bc.product_context("test-only"):
            raise ValueError("failed")
    except ValueError:
        pass
    assert bc._product_credentials.get() is None
