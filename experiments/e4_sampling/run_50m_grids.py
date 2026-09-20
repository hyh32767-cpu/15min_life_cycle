"""E50M · 五城 50m 精度网格补测(±500m 中心框,复用缓存)

目的:为地图轮廓与 50m 分辨率指标提供细粒度真值场(A 社区已有,其余五城补齐)。
设计:50m 网格 ±500m(41×41=1681 名义点),但射线轨迹/既有真值格点已覆盖部分 → 实际新增
约 300-400 对/城;全局预算 ≤ 1900 对,触顶即优雅停止(已完成的城保留)。
限流:1.2s 间隔 + 401 退避。产出:台账(E50M)+ cache;汇总写 e50m_summary.json。
"""
import json
import math
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache
from experiments.e4_sampling.run_e4 import grid_points

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GLOBAL_CAP = 2400   # 2026-08-31 额度恢复(总 5000):E50M 追加预算补完哈尔滨
EID = "E50M"
CITIES = [
    ("B", "e4_sampling/e4b.json", "北京B·东花市"),
    ("shanghai", "e10_boundary/e10x_shanghai.json", "上海·陆家嘴"),
    ("guangzhou", "e10_boundary/e10x_guangzhou.json", "广州·上下九"),
    ("chengdu", "e10_boundary/e10x_chengdu.json", "成都·九眼桥"),
    ("harbin", "e10_boundary/e10x_harbin.json", "哈尔滨·道外"),
]


def used():
    db = os.path.join(ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (EID,)).fetchone()[0]


def measure(center, points):
    todo = [p for p in points if cache.get(center, p) is None]
    done = 0
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        if used() + len(chunk) > GLOBAL_CAP:
            print(f"  ⚠️ 全局预算触顶({used()}/{GLOBAL_CAP}),停止本城后续")
            return done, False
        for attempt in range(4):
            r = bc.routematrix("walking", [center], chunk, experiment_id=EID)
            if r.ok:
                break
            if r.status == 401 and attempt < 3:
                w = [15, 30, 60][attempt]
                print(f"  ⚠️ 401 退避 {w}s")
                time.sleep(w)
                continue
            raise RuntimeError(f"matrix {r.status} {r.message}")
        for p, it in zip(chunk, bc.matrix_items(r)):
            cache.put(center, p, it["duration_s"], it["distance_m"])
        done += len(chunk)
        time.sleep(1.2)
    return done, True


def main():
    summary = {}
    for slug, fname, label in CITIES:
        if used() >= GLOBAL_CAP:
            print(f"[{label}] 预算已尽,跳过")
            break
        d = json.load(open(os.path.join(ROOT, "experiments", "results", fname), encoding="utf-8"))
        center = tuple(d["center"])
        g = grid_points(center, 50, 500)
        n_cov = sum(1 for p in g if cache.get(center, p) is not None)
        print(f"[{label}] 50m 网格 {len(g)} 点,缓存已覆盖 {n_cov}")
        n_new, ok = measure(center, g)
        n_cov2 = sum(1 for p in g if cache.get(center, p) is not None)
        print(f"  新增 {n_new} 对 → 覆盖 {n_cov2}/{len(g)}({n_cov2/len(g)*100:.0f}%)")
        summary[label] = {"target": len(g), "covered": n_cov2, "new_pairs": n_new,
                          "complete": ok}
        if not ok:
            break
    json.dump(summary, open(os.path.join(ROOT, "experiments", "results", "e4_sampling", "e50m_summary.json"),
                            "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n总消耗 {used()} 对;已写入 e50m_summary.json")


if __name__ == "__main__":
    main()
