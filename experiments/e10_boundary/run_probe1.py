# -*- coding: utf-8 -*-
"""PROBE1 · 可疑弦单探针实验(2026-09-02,~81 对)

背景:纯几何方法不可靠(docs/13 八),线性插值已是最优无偏估计。
实验:对二十社区 |Δr|>120m 的弦,在 min(r_a,r_b)×0.95 处发 1 个探针:
  超时 → 凹口确认 → 多边形该方位取 min 值;
  可达 → 无凹 → 保持线性插值。
产出:e10x_*.json 增 "probe_fix":[{bearing, side_a, side_b, verdict, fixed_r}];
      fix_metrics 对照 RMS 改善。EID=P1{idx}。断点续跑(缓存幂等)。
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache as wcache
from core.coord import dest_at
from experiments.paths import RESULTS

TH = 900
GAP = 120.0     # |Δr| 触发门限
SAFETY = 0.95   # 探针距离 = min × 0.95
FILES = {"A": ("e4_sampling", "e4.json"), "B": ("e4_sampling", "e4b.json")}
ORDER = ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian",
         "chongqing", "changsha", "wuhan", "luoyang", "kunshan", "guilin",
         "zunyi", "yiwu", "nanchang", "huilongguan", "zhangjiang",
         "zhujiangxincheng", "yulin_cd"]
GLOBAL_CAP = 200


def spent_today():
    import sqlite3
    with sqlite3.connect(os.path.join(RESULTS, "..", "logs", "calls.db")) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls "
                         "WHERE ts>=date('now','localtime')").fetchone()[0]


def run(slug, idx):
    sub, fn = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json"))
    fp = os.path.join(RESULTS, sub, fn)
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    eid = f"P1{idx:02d}"
    label = d.get("city") or d.get("community") or slug
    ks = sorted(radii)
    fixes = []
    n_probe = 0

    for i in range(len(ks)):
        b_a = ks[i]
        b_b = ks[(i + 1) % len(ks)]
        r_a, r_b = radii[b_a], radii[b_b]
        if abs(r_a - r_b) <= GAP:
            continue
        mb = ((b_a + b_b) / 2) if b_b > b_a else ((b_a + b_b + 360) / 2) % 360
        probe_d = min(r_a, r_b) * SAFETY
        p = dest_at(center[1], center[0], mb, probe_d)
        # 缓存优先
        row = wcache.get(center, p)
        if row is None:
            if spent_today() >= GLOBAL_CAP:
                print(f"[{label}] 预算触顶,停止", flush=True)
                break
            r2 = bc.routematrix("walking", [center], [p], experiment_id=eid)
            if not r2.ok:
                print(f"  [{label}] {mb:.1f}° API {r2.status},跳过", flush=True)
                continue
            it = next(iter(bc.matrix_items(r2)), None)
            if it and it.get("duration_s") is not None:
                wcache.put(center, p, it["duration_s"], it.get("distance_m"))
                n_probe += 1
            time.sleep(0.5)
        row = wcache.get(center, p)
        t = row[0] if row else None
        if t is None:
            continue
        verdict = "凹" if t > TH else "凸"
        fixed_r = min(r_a, r_b) if verdict == "凹" else max(r_a, r_b)
        fixes.append({"bearing": round(mb, 2), "a": round(b_a, 1), "b": round(b_b, 1),
                      "r_a": round(r_a), "r_b": round(r_b),
                      "probe_t": round(t), "verdict": verdict,
                      "suggest_r": round(fixed_r)})

    d["probe_fix"] = fixes
    n_cavity = sum(1 for f in fixes if f["verdict"] == "凹")
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{label}] 探针 {n_probe} 对 | 凹 {n_cavity} / 凸 {len(fixes)-n_cavity}"
          f" / 共 {len(fixes)} 处", flush=True)


def main():
    only = set(sys.argv[1:])
    for idx, slug in enumerate(ORDER):
        if only and slug not in only:
            continue
        if spent_today() >= GLOBAL_CAP:
            print("全局预算触顶,停止", flush=True)
            break
        try:
            run(slug, idx)
        except Exception as e:
            print(f"[{slug}] 失败:{str(e)[:120]}", flush=True)
    print(f"\nPROBE1 今日总耗 {spent_today()} 对(含其他实验)", flush=True)


if __name__ == "__main__":
    main()
