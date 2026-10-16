# -*- coding: utf-8 -*-
"""产品级 API 缓存:规范化请求 hash -> 原始响应/元数据。

与 experiments/logs/cache.db 隔离。缓存 key 包含接口版本、坐标系和所有
影响结果的请求参数;响应 hash 可追踪。本模块不接触百度密钥。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_cache (
    request_hash TEXT PRIMARY KEY,
    interface TEXT NOT NULL,
    interface_version TEXT NOT NULL,
    crs TEXT NOT NULL,
    params_json TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    body_json TEXT NOT NULL,
    status INTEGER NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    source_kind TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_cache_interface ON api_cache(interface);
CREATE TABLE IF NOT EXISTS matrix_cells (
    origin_key TEXT NOT NULL, destination_key TEXT NOT NULL,
    request_hash TEXT NOT NULL, item_json TEXT NOT NULL,
    PRIMARY KEY(origin_key, destination_key, request_hash)
);
CREATE TABLE IF NOT EXISTS matrix_indexed (
    request_hash TEXT PRIMARY KEY, response_hash TEXT NOT NULL
);
"""


def _canonical(value: Any) -> Any:
    """把参数/响应转成稳定 JSON 结构;不包含任何密钥。"""
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def request_hash(interface: str, interface_version: str, crs: str,
                 params: Dict[str, Any]) -> str:
    payload = {
        "interface": interface,
        "interfaceVersion": interface_version,
        "crs": crs,
        "params": params,
    }
    return sha256_text(canonical_json(payload))


def response_hash(body: Any) -> str:
    return sha256_text(canonical_json(body))


@dataclass(frozen=True)
class CacheRecord:
    request_hash: str
    interface: str
    interface_version: str
    crs: str
    params: Dict[str, Any]
    response_hash: str
    body: Dict[str, Any]
    status: int
    message: str
    latency_ms: int
    source_kind: str
    fetched_at: str
    expires_at: Optional[str]

    @property
    def expired(self) -> bool:
        if not self.expires_at:
            return False
        return _now() > datetime.fromisoformat(self.expires_at)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApiCache:
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

    def get(self, key: str, *, fresh_only: bool = True) -> Optional[CacheRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_cache WHERE request_hash=?", (key,)
            ).fetchone()
        if row is None:
            return None
        record = CacheRecord(
            request_hash=row["request_hash"],
            interface=row["interface"],
            interface_version=row["interface_version"],
            crs=row["crs"],
            params=json.loads(row["params_json"]),
            response_hash=row["response_hash"],
            body=json.loads(row["body_json"]),
            status=row["status"],
            message=row["message"],
            latency_ms=row["latency_ms"],
            source_kind=row["source_kind"],
            fetched_at=row["fetched_at"],
            expires_at=row["expires_at"],
        )
        if fresh_only and record.expired:
            return None
        return record

    def put(self, *, interface: str, interface_version: str, crs: str,
            params: Dict[str, Any], body: Dict[str, Any], status: int,
            message: str = "", latency_ms: int = 0,
            source_kind: str = "live-api", ttl_s: Optional[float] = None,
            fetched_at: Optional[datetime] = None) -> CacheRecord:
        key = request_hash(interface, interface_version, crs, params)
        fetched = fetched_at or _now()
        expires_at = None
        if ttl_s is not None:
            expires_at = (fetched + timedelta(seconds=ttl_s)).isoformat()
        r_hash = response_hash(body)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO api_cache
                   (request_hash, interface, interface_version, crs, params_json,
                    response_hash, body_json, status, message, latency_ms,
                    source_kind, fetched_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, interface, interface_version, crs, canonical_json(params),
                 r_hash, canonical_json(body), status, message, latency_ms,
                 source_kind, fetched.isoformat(), expires_at),
            )
        return self.get(key, fresh_only=False)  # type: ignore[return-value]

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0])

    def matrix_cells(self, origins: list, destinations: list) -> dict:
        """复用有效原始矩阵响应里的有向 OD；精确坐标，不吸附到邻近格点。

        源响应更新/过期同步失效；旧产品库按需建立索引，不复制研究缓存。
        只索引有合法时长的 cell，缺项/非法值不能成为可达测值。
        """
        def point_key(point):
            return canonical_json([float(point[0]), float(point[1])])

        found = {}
        with self._lock, self._connect() as conn:
            rows = conn.execute("""SELECT c.* FROM api_cache c LEFT JOIN matrix_indexed i
                ON c.request_hash=i.request_hash WHERE c.interface='matrix_walking'
                AND c.interface_version='v2' AND c.crs='BD09'
                AND (i.response_hash IS NULL OR i.response_hash!=c.response_hash)""").fetchall()
            for row in rows:
                conn.execute("DELETE FROM matrix_cells WHERE request_hash=?", (row['request_hash'],))
                params = json.loads(row['params_json'])
                body = json.loads(row['body_json'])
                starts, ends = params.get('origins', []), params.get('destinations', [])
                if row['status'] == 0 and params.get('mode') == 'walking' and starts and ends:
                    items = body.get('result') if isinstance(body.get('result'), list) else []
                    for index, item in enumerate(items[:len(starts) * len(ends)]):
                        duration_object = item.get('duration') if isinstance(item, dict) else None
                        duration = duration_object.get('value') if isinstance(duration_object, dict) else None
                        if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                                and math.isfinite(duration) and duration >= 0):
                            start_index, end_index = divmod(index, len(ends))
                            conn.execute("INSERT OR REPLACE INTO matrix_cells VALUES (?,?,?,?)",
                                         (point_key(starts[start_index]), point_key(ends[end_index]),
                                          row['request_hash'], canonical_json(item)))
                conn.execute("INSERT OR REPLACE INTO matrix_indexed VALUES (?,?)",
                             (row['request_hash'], row['response_hash']))
            for i, start in enumerate(origins):
                for j, end in enumerate(destinations):
                    row = conn.execute("""SELECT m.item_json,c.request_hash,c.response_hash,c.expires_at
                        FROM matrix_cells m JOIN api_cache c ON m.request_hash=c.request_hash
                        WHERE m.origin_key=? AND m.destination_key=? AND c.status=0
                        AND (c.expires_at IS NULL OR c.expires_at>?)
                        ORDER BY c.fetched_at DESC,c.request_hash LIMIT 1""",
                        (point_key(start), point_key(end), _now().isoformat())).fetchone()
                    if row:
                        found[(i, j)] = {'item': json.loads(row['item_json']),
                                         'requestHash': row['request_hash'],
                                         'responseHash': row['response_hash'], 'expiresAt': row['expires_at']}
        return found
