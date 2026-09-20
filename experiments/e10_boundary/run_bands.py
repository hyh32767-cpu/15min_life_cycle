# -*- coding: utf-8 -*-
"""BAND · 复通带精测 v2(每向多个 15min 点)

v1 教训:二分方向写反 + CityRunner 预算按全局 EID 计数导致串城截断——全部返工。
v2:显式两个方向函数;每任务独立 EID(BAND{slug 简写}{方位})+ cap 60;
    探针失败(None)即中止该任务并如实记录,不写垃圾值。
语义:pocket = {bearing, wedge_deg, r, gap:[g0,g1], outer}
    r=主边界;gap=隔离带[g0,g1](g0=最远连续可达,g1=最近复通);outer=第二边界。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.paths import RESULTS

TH = 900
TASKS = [
    ("harbin", 33.7, 561, (650, 701)),
    ("harbin", 45.0, 608, (650, 684)),
    ("chongqing", 153.4, 298, (335, 447)),
    ("changsha", 157.5, 467, (500, 615)),
    ("guilin", 163.1, 416, (500, 540)),
    ("zunyi", 135.0, 598, (650, 707)),
]


def make(R, brg):
    def pr(d):
        p = R.endpoint(brg, d)
        R.measure([p])
        return R.t_of(p)
    return pr


def farthest_ok(pr, lo, hi, tol=25.0):
    """[lo,hi] 内找最远 ≤TH(lo 应为 OK)。"""
    while hi - lo > tol:
        m = (lo + hi) / 2
        t = pr(m)
        if t is None:
            return None
        if t <= TH:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def nearest_x(pr, lo, hi, tol=25.0):
    """[lo,hi] 内找最近 >TH(lo 应为 X)。"""
    while hi - lo > tol:
        m = (lo + hi) / 2
        t = pr(m)
        if t is None:
            return None
        if t > TH:
            hi = m
        else:
            lo = m
    return (lo + hi) / 2


def run(slug, brg, r, gap_hint, task_no):
    fp = os.path.join(RESULTS, "e10_boundary", f"e10x_{slug}.json")
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    R = CityRunner(f"BAND{task_no}", center, cap=60)
    pr = make(R, brg)
    g0h, g1h = gap_hint

    g0 = farthest_ok(pr, r, g0h + 10)                 # 隔离带内缘(最远连续可达)
    g1 = nearest_x(pr, g1h + 10 if g1h < 1390 else 1390, 1390) if False else None
    # 复通点:在 g1h 之后最近的 OK —— 先确认 g1h+40 处 OK,再向内找最近 X
    t_check = pr(min(g1h + 40, 1380))
    g1 = None
    outer = None
    if t_check is not None and t_check <= TH:
        g1 = nearest_x(pr, g0 + 10, min(g1h + 40, 1380))   # 隔离带外缘
        if g1:
            outer = farthest_ok(pr, g1 + 10, 1390)          # 第二边界
    ok = g0 is not None and g1 is not None
    if not ok:
        print(f"[{d['city']} {brg}°] 探针不足,如实放弃(g0={g0},g1={g1})")
        return
    # 宽度:±5.6° 在复通段中点是否可达
    mid = (g1 + (outer or g1 + 100)) / 2
    wedge = 2.8
    for nb in (brg - 5.6, brg + 5.6):
        p = R.endpoint(nb, mid)
        R.measure([p])
        t = R.t_of(p)
        if t is not None and t <= TH:
            wedge = 8.4
            break
    pk = {"bearing": round(brg, 1), "wedge_deg": wedge, "r": round(r),
          "gap": [round(g0), round(g1)], "outer": round(outer) if outer else None}
    pockets = [p for p in (d.get("pockets") or [])
               if not (isinstance(p.get("gap"), list) and abs(p["bearing"] - brg) < 1.0)]
    pockets.append(pk)
    d["pockets"] = pockets
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{d['city']} {brg}°] r={r} | 隔离带 {pk['gap'][0]}-{pk['gap'][1]}m | "
          f"复通段 → {pk['outer']}m | 宽 ±{wedge}° | 耗 {R.used()} 对")


def main():
    for i, (slug, brg, r, gap) in enumerate(TASKS):
        try:
            run(slug, brg, r, gap, i)
        except Exception as e:
            print(f"[{slug} {brg}°] 失败:{str(e)[:120]}")


if __name__ == "__main__":
    main()
