"""调用台账:所有 API 调用写入 SQLite,配额可核算、实验可复现。实验期用 SQLite 代替 Redis。"""
import json
import os
import sqlite3
import threading
import time

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "experiments", "logs", "calls.db")
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY,
  ts TEXT,
  experiment_id TEXT,
  kind TEXT,                -- walk / batch_walk / poi / geocode / reverse_geocode
  o_lat REAL, o_lng REAL, d_lat REAL, d_lng REAL,
  n_pairs INTEGER,
  cache_hit INTEGER,
  latency_ms INTEGER,
  status INTEGER,           -- HTTP/业务 status: 0 = 成功
  message TEXT,
  duration_s REAL,
  distance_m REAL,
  raw_hash TEXT
)
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.execute(_SCHEMA)
    return c


def log_call(**kw) -> None:
    with _lock:
        with _conn() as c:
            c.execute(
                "INSERT INTO calls (ts, experiment_id, kind, o_lat, o_lng, d_lat, d_lng,"
                " n_pairs, cache_hit, latency_ms, status, message, duration_s, distance_m, raw_hash)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    kw.get("experiment_id"), kw.get("kind"),
                    kw.get("o_lat"), kw.get("o_lng"), kw.get("d_lat"), kw.get("d_lng"),
                    kw.get("n_pairs"), int(bool(kw.get("cache_hit"))),
                    kw.get("latency_ms"), kw.get("status"), str(kw.get("message") or "")[:200],
                    kw.get("duration_s"), kw.get("distance_m"),
                    kw.get("raw_hash"),
                ),
            )


def quota_used(experiment_id: str = None) -> int:
    """统计某实验(或全部)的累计调用次数(含失败——失败同样烧配额)。"""
    with _lock, _conn() as c:
        if experiment_id:
            row = c.execute("SELECT COUNT(*) FROM calls WHERE experiment_id=?",
                            (experiment_id,)).fetchone()
        else:
            row = c.execute("SELECT COUNT(*) FROM calls").fetchone()
    return row[0]


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    """配额纪律:runner 声明预算,台账计数超限立即 abort。"""

    def __init__(self, experiment_id: str, max_calls: int):
        self.experiment_id = experiment_id
        self.max_calls = max_calls

    def check(self):
        used = quota_used(self.experiment_id)
        if used >= self.max_calls:
            raise BudgetExceeded(
                f"[{self.experiment_id}] 预算 {self.max_calls} 次已耗尽(台账计数 {used}),停止执行")
