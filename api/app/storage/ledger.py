# -*- coding: utf-8 -*-
"""产品级调用账本:本次 live 请求、cache hit 和历史实验分开统计。

每次调用一行,记录 traceId、stage、接口、requestHash、cacheHit、
status、requests、pairs、latencyMs、budgetRemaining 和 responseHash。
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    interface TEXT NOT NULL,
    request_hash TEXT NOT NULL DEFAULT '',
    cache_hit INTEGER NOT NULL DEFAULT 0,
    status INTEGER NOT NULL,
    requests INTEGER NOT NULL DEFAULT 1,
    pairs INTEGER NOT NULL DEFAULT 1,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    budget_remaining INTEGER,
    message TEXT NOT NULL DEFAULT '',
    response_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_api_calls_trace ON api_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_api_calls_interface ON api_calls(interface);
"""


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LedgerBreakdown:
    """按某一维度（stage 或 interface）聚合的账本行。"""
    key: str
    rows: int
    requests: int
    live_requests: int
    cache_hits: int
    pairs: int
    errors: int
    latency_ms: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "rows": self.rows,
            "requests": self.requests,
            "liveRequests": self.live_requests,
            "cacheHits": self.cache_hits,
            "pairs": self.pairs,
            "errors": self.errors,
            "latencyMs": self.latency_ms,
        }


@dataclass(frozen=True)
class LedgerSummary:
    trace_id: Optional[str]
    rows: int
    requests: int
    live_requests: int
    cache_hits: int
    pairs: int
    errors: int
    latency_ms: int
    by_stage: tuple = ()
    by_interface: tuple = ()

    def as_dict(self) -> Dict[str, Any]:
        payload = {
            "traceId": self.trace_id,
            "rows": self.rows,
            "requests": self.requests,
            "liveRequests": self.live_requests,
            "cacheHits": self.cache_hits,
            "pairs": self.pairs,
            "errors": self.errors,
            "latencyMs": self.latency_ms,
        }
        if self.by_stage:
            payload["byStage"] = [item.as_dict() for item in self.by_stage]
        if self.by_interface:
            payload["byInterface"] = [item.as_dict() for item in self.by_interface]
        return payload


class ProductLedger:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        directory = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(directory, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, *, trace_id: str, interface: str, status: int,
               stage: str = "", request_hash: str = "", cache_hit: bool = False,
               requests: int = 1, pairs: int = 1, latency_ms: int = 0,
               budget_remaining: Optional[int] = None, message: str = "",
               response_hash: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO api_calls
                   (trace_id, stage, interface, request_hash, cache_hit, status,
                    requests, pairs, latency_ms, budget_remaining, message,
                    response_hash, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (trace_id, stage, interface, request_hash, int(bool(cache_hit)),
                 status, requests, pairs, latency_ms, budget_remaining,
                 message[:200], response_hash, _now_iso()),
            )

    def live_pairs(self, trace_id: str) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute('SELECT COALESCE(SUM(pairs),0) FROM api_calls WHERE trace_id=? AND cache_hit=0',
                                    (trace_id,)).fetchone()[0])

    def summary(self, trace_id: Optional[str] = None, *,
                group_by: Optional[str] = None) -> LedgerSummary:
        where = " WHERE trace_id=?" if trace_id else ""
        args = (trace_id,) if trace_id else ()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"""SELECT COUNT(*) AS rows,
                           COALESCE(SUM(requests),0) AS requests,
                           COALESCE(SUM(CASE WHEN cache_hit=0 THEN requests ELSE 0 END),0) AS live_requests,
                           COALESCE(SUM(CASE WHEN cache_hit=1 THEN requests ELSE 0 END),0) AS cache_hits,
                           COALESCE(SUM(pairs),0) AS pairs,
                           COALESCE(SUM(CASE WHEN status!=0 THEN 1 ELSE 0 END),0) AS errors,
                           COALESCE(SUM(latency_ms),0) AS latency_ms
                    FROM api_calls{where}""", args).fetchone()
            by_stage: tuple = ()
            by_interface: tuple = ()
            if group_by in {"stage", "both"}:
                by_stage = tuple(self._breakdown(conn, "stage", where, args))
            if group_by in {"interface", "both"}:
                by_interface = tuple(self._breakdown(conn, "interface", where, args))
        return LedgerSummary(
            trace_id=trace_id,
            rows=int(row["rows"]),
            requests=int(row["requests"]),
            live_requests=int(row["live_requests"]),
            cache_hits=int(row["cache_hits"]),
            pairs=int(row["pairs"]),
            errors=int(row["errors"]),
            latency_ms=int(row["latency_ms"]),
            by_stage=by_stage,
            by_interface=by_interface,
        )

    @staticmethod
    def _breakdown(conn: sqlite3.Connection, column: str,
                   where: str, args: tuple) -> list:
        rows = conn.execute(
            f"""SELECT {column} AS key,
                       COUNT(*) AS rows,
                       COALESCE(SUM(requests),0) AS requests,
                       COALESCE(SUM(CASE WHEN cache_hit=0 THEN requests ELSE 0 END),0) AS live_requests,
                       COALESCE(SUM(CASE WHEN cache_hit=1 THEN requests ELSE 0 END),0) AS cache_hits,
                       COALESCE(SUM(pairs),0) AS pairs,
                       COALESCE(SUM(CASE WHEN status!=0 THEN 1 ELSE 0 END),0) AS errors,
                       COALESCE(SUM(latency_ms),0) AS latency_ms
                FROM api_calls{where}
                GROUP BY {column} ORDER BY {column}""", args).fetchall()
        return [LedgerBreakdown(
            key=str(item["key"] or ""),
            rows=int(item["rows"]),
            requests=int(item["requests"]),
            live_requests=int(item["live_requests"]),
            cache_hits=int(item["cache_hits"]),
            pairs=int(item["pairs"]),
            errors=int(item["errors"]),
            latency_ms=int(item["latency_ms"]),
        ) for item in rows]
