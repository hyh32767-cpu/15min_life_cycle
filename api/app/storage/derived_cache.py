# -*- coding: utf-8 -*-
"""派生缓存:只缓存由 API 响应/算法/假设/事件版本共同决定的结果。

任一依赖变化(源响应 hash、阈值、方向、算法版本、假设版本、事件版本)
都必须产生新 key;模拟停留变化不应触发新百度调用。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .api_cache import canonical_json, sha256_text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_cache (
    derived_key TEXT PRIMARY KEY,
    algorithm TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_derived_algorithm ON derived_cache(algorithm);
-- F66：taskId/reportId -> derived_key 别名索引；缓存命中生成的新 taskId 也登记，
-- 报告重取按索引读取，不再全表扫描设限。
CREATE TABLE IF NOT EXISTS derived_task_index (
    task_id TEXT PRIMARY KEY,
    derived_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def derived_key(*, algorithm: str, algorithm_version: str,
                input_hashes: Dict[str, str], params: Dict[str, Any],
                assumptions_version: str = "", event_version: str = "") -> str:
    payload = {
        "algorithm": algorithm,
        "algorithmVersion": algorithm_version,
        "inputHashes": input_hashes,
        "params": params,
        "assumptionsVersion": assumptions_version,
        "eventVersion": event_version,
    }
    return sha256_text(canonical_json(payload))


@dataclass(frozen=True)
class DerivedRecord:
    key: str
    algorithm: str
    algorithm_version: str
    dependencies: Dict[str, Any]
    result: Any
    created_at: str

    def is_expired(self, *, ttl_s: float) -> bool:
        try:
            created = datetime.fromisoformat(self.created_at)
        except ValueError:
            return True
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        return age > ttl_s

class DerivedCache:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, key: str) -> Optional[DerivedRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM derived_cache WHERE derived_key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        return DerivedRecord(
            key=row["derived_key"],
            algorithm=row["algorithm"],
            algorithm_version=row["algorithm_version"],
            dependencies=json.loads(row["dependencies_json"]),
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
        )

    def put(self, *, key: str, algorithm: str, algorithm_version: str,
            dependencies: Dict[str, Any], result: Any) -> DerivedRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO derived_cache
                   (derived_key, algorithm, algorithm_version, dependencies_json,
                    result_json, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (key, algorithm, algorithm_version, canonical_json(dependencies),
                 canonical_json(result), datetime.now(timezone.utc).isoformat()),
            )
        return self.get(key)  # type: ignore[return-value]

    def register_task(self, task_id: str, key: str) -> None:
        """F66：登记 taskId 别名（含缓存命中生成的新 taskId）。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO derived_task_index
                   (task_id, derived_key, created_at) VALUES (?,?,?)""",
                (task_id, key, datetime.now(timezone.utc).isoformat()),
            )

    def get_by_task(self, task_id: str) -> Optional[DerivedRecord]:
        """F66：按 taskId/reportId 重取报告。先查别名索引，旧库无索引时回退全表扫描。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT derived_key FROM derived_task_index WHERE task_id=?", (task_id,)
            ).fetchone()
            key = row["derived_key"] if row else None
        if key is not None:
            record = self.get(key)
            if record is not None:
                return record
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM derived_cache WHERE algorithm=? ORDER BY created_at DESC",
                ("isochrone-batched",),
            ).fetchall()
        for row in rows:
            try:
                result = json.loads(row["result_json"])
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict) and result.get("taskId") == task_id:
                return DerivedRecord(
                    key=row["derived_key"],
                    algorithm=row["algorithm"],
                    algorithm_version=row["algorithm_version"],
                    dependencies=json.loads(row["dependencies_json"]),
                    result=result,
                    created_at=row["created_at"],
                )
        return None

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM derived_cache").fetchone()[0])
