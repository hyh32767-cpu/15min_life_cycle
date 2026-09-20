# -*- coding: utf-8 -*-
"""E11 · 邻近点缓存:跨源复用标定(2026-09-01,live ~110 对)

问题:cache 以 (origin,dest) 为键,源点平移几十米即全失效。
实验(哈尔滨,场最厚):取中心 A 已缓存的 50 个 dest(分层抽样);
  B = A 东北 ~120m;C = A 东北 ~300m。实测 B→dests、C→dests,
  与缓存 A→dests 比对,得 ΔT(源距) 包络(P50/P95),回答"源点平移多少米内可复用"。
产出:results/e0_instrument/e11_neighbors.json + 复用规则建议。
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache as wcache
from core.coord import dest_at
from experiments.paths import RESULTS

TH = 900
EID = "E11X"
A = (45.787628862747844, 126.64736136918812)
N = 50


def main():
    # 从缓存抽 A 的 dest(按距离分层)
    import sqlite3
    con = sqlite3.connect(os.path.join(RESULTS, "..", "logs", "cache.db"))
    rows = con.execute("SELECT d_lat,d_lng,duration_s FROM walk_times "
                       "WHERE o_lat BETWEEN ?-1e-4 AND ?+1e-4 "
                       "AND o_lng BETWEEN ?-1e-4 AND ?+1e-4",
                       (A[0], A[0], A[1], A[1])).fetchall()
    rng = random.Random(5)
    picked = []
    for lo, hi in [(200, 500), (500, 800), (800, 1100), (1100, 1400)]:
        band = [r for r in rows
                if lo <= math.hypot((r[0] - A[0]) * 111320,
                                    (r[1] - A[1]) * 111320 * math.cos(math.radians(A[0]))) < hi
                and r[2] is not None]
        picked += rng.sample(band, min(12, len(band)))
    picked = picked[:N]
    print(f"抽样 {len(picked)} 个 dest(200-1400m 分层)")

    B = dest_at(A[1], A[0], 45, 120)
    C = dest_at(A[1], A[0], 45, 300)
    out_rows = []
    for name, O in (("B120", B), ("C300", C)):
        for i in range(0, len(picked), 50):
            chunk = [(r[0], r[1]) for r in picked[i:i + 50]]
            todo = [p for p in chunk if wcache.get(O, p) is None]
            if todo:
                r2 = bc.routematrix("walking", [O], todo, experiment_id=EID)
                if not r2.ok:
                    print(f"  [{name}] matrix {r2.status} {r2.message[:40]}")
                    continue
                for p, it in zip(todo, bc.matrix_items(r2)):
                    wcache.put(O, p, it["duration_s"], it.get("distance_m"))
        for dlat, dlng, tA in picked:
            row = wcache.get(O, (dlat, dlng))
            if row and row[0] is not None and tA is not None:
                out_rows.append({"org": name, "tA": tA, "tO": row[0],
                                 "d": round(math.hypot((dlat - A[0]) * 111320,
                                                       (dlng - A[1]) * 111320
                                                       * math.cos(math.radians(A[0]))))})

    # 包络
    stats = {}
    for name in ("B120", "C300"):
        dts = sorted(abs(r["tO"] - r["tA"]) for r in out_rows if r["org"] == name)
        cls = sum(1 for r in out_rows if r["org"] == name
                  and (r["tA"] <= TH) != (r["tO"] <= TH))
        if dts:
            stats[name] = {"n": len(dts), "p50": dts[len(dts) // 2],
                           "p95": dts[int(0.95 * len(dts))],
                           "max": dts[-1], "分类翻转数": cls,
                           "翻转率": round(cls / len(dts), 3)}
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    json.dump({"A": list(A), "B": list(B), "C": list(C), "rows": out_rows,
               "stats": stats},
              open(os.path.join(RESULTS, "e0_instrument", "e11_neighbors.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写 results/e0_instrument/e11_neighbors.json")


if __name__ == "__main__":
    main()
