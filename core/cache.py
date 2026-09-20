"""持久化缓存:步行测时结果按 (origin, dest, mode) 去重。

实验期用 SQLite(设计文档 09:产品期换 Redis,行为一致)。
重复查看/重跑同一社区 → API 调用 ≈ 0。
"""
import os
import sqlite3
import threading

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "experiments", "logs", "cache.db")
_lock = threading.Lock()


def _conn():
    os.makedirs(os.path.dirname(_DB), exist_ok=True)
    c = sqlite3.connect(_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS walk_times (
        o_lat REAL, o_lng REAL, d_lat REAL, d_lng REAL, mode TEXT,
        duration_s REAL, distance_m REAL,
        PRIMARY KEY (o_lat, o_lng, d_lat, d_lng, mode))""")
    return c


def get(o, d, mode="walking"):
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT duration_s, distance_m FROM walk_times"
            " WHERE o_lat=? AND o_lng=? AND d_lat=? AND d_lng=? AND mode=?",
            (round(o[0], 6), round(o[1], 6), round(d[0], 6), round(d[1], 6), mode)
        ).fetchone()
    return row  # (duration, distance) or None


def put(o, d, duration_s, distance_m, mode="walking"):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO walk_times VALUES (?,?,?,?,?,?,?)",
                  (round(o[0], 6), round(o[1], 6), round(d[0], 6), round(d[1], 6),
                   mode, duration_s, distance_m))


def size():
    with _lock, _conn() as c:
        return c.execute("SELECT COUNT(*) FROM walk_times").fetchone()[0]
