# -*- coding: utf-8 -*-
"""PKRX · 口袋探测并入 + ρ 热弦强制细分(2026-08-31,~110 对)

针对 fix_metrics 定位的带外真误差簇:
  A) ρ 热弦细分:rho.hot_chords(已实测的绕行异常弦)无条件在中点方位插向重二分
     ——哈尔滨 224°/+199m 大凸包即此类;
  B) 口袋探测:16 均匀方位在 1.25×r 处单发探针,命中(≤15min)则向内/向外
     定口袋边界 + 邻近两向定宽度——义乌 90°/-342m、洛阳 0°/-261m、重庆 114°/-135m
     的远端 FN 即此类(桥廊/独立可达块,多边形天然不含)。
产出:e10x_{slug}.json 增 "pockets":[{bearing,wedge_deg,inner_m,outer_m}],
     radii 并入 ρ 插向;EID=PKRX。城:义乌/洛阳/重庆/哈尔滨。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.paths import RESULTS

TH = 900
EID = "PKRX"
CITIES = ["yiwu", "luoyang", "chongqing", "harbin"]


def probe(R, b, d):
    p = R.endpoint(b, d)
    R.measure([p])
    return R.t_of(p)


def bisect_between(R, b, lo, hi, want_in, tol=25.0):
    """在 [lo,hi] 内二分:want_in=True 找最远 ≤TH,否则找最近 >TH。"""
    while hi - lo > tol:
        m = (lo + hi) / 2
        t = probe(R, b, m)
        if t is None:
            return None
        ok = t <= TH
        if ok == want_in:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def run(slug):
    fp = os.path.join(RES_DIR, f"e10x_{slug}.json")
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    R = CityRunner(EID, center, cap=260)
    print(f"\n===== {d['city']} =====")

    # A) ρ 热弦强制细分
    hot = (d.get("rho") or {}).get("hot_chords") or []
    inserted = 0
    for mb in hot:
        if any(abs(mb - b) < 0.6 or abs(mb - b - 360) < 0.6 for b in radii):
            continue
        before = R.used()
        new = R.bisect([mb])
        radii.update(new)
        inserted += 1
        print(f"  ρ热弦 {mb}° 插向(半径 {new[mb]:.0f}m,+{R.used()-before} 对)")
    if not inserted:
        print("  ρ热弦:无需插(已有向或无热弦)")

    # B) 口袋探测
    pockets = d.get("pockets") or []
    for i in range(16):
        b = i * 22.5
        r = R.r_at(b, radii)
        t = probe(R, b, r * 1.25)
        if t is None or t > TH:
            continue
        # 命中:向外找外缘,向内找隔离带(第一个 >TH 的位置)
        outer = bisect_between(R, b, r * 1.25, r * 1.6, want_in=True)
        inner_gap = bisect_between(R, b, r, r * 1.25, want_in=False)  # 最近 >TH
        # 宽度:邻向 ±11.25 是否也可达
        w = 5.6
        for nb in (b - 11.25, b + 11.25):
            tn = probe(R, nb, R.r_at(nb, radii) * 1.25)
            if tn is not None and tn <= TH:
                w = 11.25
                break
        pockets.append({"bearing": round(b, 1), "wedge_deg": w,
                        "inner_m": round(inner_gap or r), "outer_m": round(outer or r * 1.25),
                        "probe_t": round(t)})
        print(f"  口袋@{b}°: 隔离带起 {inner_gap and round(inner_gap)}m → 外缘 "
              f"{outer and round(outer)}m(宽 ±{w}°,1.25r 处 {t:.0f}s)")

    d["radii"] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    d["rays"] = len(radii)
    d["pockets"] = pockets
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  已更新({len(radii)} 向,{len(pockets)} 口袋,本城新耗 {R.used()} 对)")


RES_DIR = os.path.join(RESULTS, "e10_boundary")


def main():
    for slug in CITIES:
        try:
            run(slug)
        except Exception as e:
            print(f"[{slug}] 失败:{str(e)[:150]}")


if __name__ == "__main__":
    main()
