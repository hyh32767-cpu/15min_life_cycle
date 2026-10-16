# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

from api.app.storage.api_cache import ApiCache, request_hash, response_hash
from api.app.storage.ledger import ProductLedger, new_trace_id


def test_request_hash_is_normalized_and_scoped():
    a = request_hash("place_search", "v2", "BD09", {"query": "药店", "page": 0})
    b = request_hash("place_search", "v2", "BD09", {"page": 0, "query": "药店"})
    c = request_hash("place_search", "v2", "BD09", {"query": "药店", "page": 1})
    d = request_hash("place_search", "v3", "BD09", {"query": "药店", "page": 0})
    e = request_hash("place_search", "v2", "GCJ02", {"query": "药店", "page": 0})
    assert a == b
    assert a != c and a != d and a != e


def test_api_cache_roundtrip_and_ttl(tmp_path):
    cache = ApiCache(str(tmp_path / "cache.db"))
    body = {"status": 0, "result": {"name": "药店"}}
    record = cache.put(
        interface="place_search",
        interface_version="v2",
        crs="BD09",
        params={"query": "药店", "page_num": 0},
        body=body,
        status=0,
        message="ok",
        latency_ms=120,
        ttl_s=3600,
    )
    assert record.response_hash == response_hash(body)
    fetched = cache.get(record.request_hash)
    assert fetched is not None
    assert fetched.body == body
    assert fetched.source_kind == "live-api"
    assert fetched.expired is False
    assert cache.count() == 1

    expired = cache.put(
        interface="place_search",
        interface_version="v2",
        crs="BD09",
        params={"query": "过期", "page_num": 0},
        body={"status": 0},
        status=0,
        ttl_s=-1,
    )
    assert cache.get(expired.request_hash) is None
    assert cache.get(expired.request_hash, fresh_only=False) is not None


def test_product_ledger_separates_live_and_cache_hits(tmp_path):
    ledger = ProductLedger(str(tmp_path / "ledger.db"))
    trace = new_trace_id()
    ledger.record(trace_id=trace, interface="geocode", status=0, stage="A1",
                  requests=1, pairs=1, latency_ms=80,
                  response_hash="rh1", request_hash="rq1")
    ledger.record(trace_id=trace, interface="matrix_walking", status=0, stage="A3",
                  requests=1, pairs=4, latency_ms=200, response_hash="rh2",
                  request_hash="rq2")
    ledger.record(trace_id=trace, interface="place_search", status=0, stage="A2",
                  cache_hit=True, requests=1, pairs=1, latency_ms=3,
                  response_hash="rh3", request_hash="rq3")
    ledger.record(trace_id=trace, interface="place_detail", status=4, stage="A2",
                  requests=1, pairs=1, latency_ms=60, message="quota")

    summary = ledger.summary(trace)
    assert summary.rows == 4
    assert summary.requests == 4
    assert summary.live_requests == 3
    assert summary.cache_hits == 1
    assert summary.pairs == 7
    assert summary.errors == 1
    assert summary.latency_ms == 343
    assert summary.as_dict()["cacheHits"] == 1


def test_ledger_summary_splits_isochrone_vs_plan_stages(tmp_path):
    ledger = ProductLedger(str(tmp_path / "ledger.db"))
    trace = new_trace_id()
    ledger.record(trace_id=trace, interface="matrix_walking", status=0, stage="A3",
                  requests=1, pairs=4, latency_ms=200,
                  response_hash="rh-plan", request_hash="rq-plan")
    ledger.record(trace_id=trace, interface="matrix_walking", status=0, stage="isochrone",
                  requests=1, pairs=6, latency_ms=150,
                  response_hash="rh-iso", request_hash="rq-iso")

    summary = ledger.summary(trace, group_by="both")
    assert summary.rows == 2
    assert summary.pairs == 10
    by_stage = {item.key: item for item in summary.by_stage}
    assert by_stage["A3"].pairs == 4
    assert by_stage["isochrone"].pairs == 6
    by_interface = {item.key: item for item in summary.by_interface}
    assert by_interface["matrix_walking"].rows == 2
    payload = summary.as_dict()
    assert {row["key"] for row in payload["byStage"]} == {"A3", "isochrone"}
    assert payload["byInterface"][0]["pairs"] == 10
    # 默认口径保持不变：不分组时不返回 breakdown 键。
    assert "byStage" not in ledger.summary(trace).as_dict()


def test_expiry_uses_explicit_timestamp(tmp_path):
    cache = ApiCache(str(tmp_path / "cache.db"))
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    record = cache.put(
        interface="x", interface_version="v1", crs="BD09",
        params={"a": 1}, body={"ok": True}, status=0,
        ttl_s=60, fetched_at=past,
    )
    assert record.expired is True
    assert cache.get(record.request_hash) is None
