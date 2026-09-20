# -*- coding: utf-8 -*-
"""FIXM · 评估修复 + 融合分类器选优(零 API,2026-08-31)

背景:run_small5 落盘 IoU 与其自身 fp/fn 不自洽(义乌 0.781 vs 应为 0.918),
且未区分"格网量化带内误差"与真方法误差。本脚本:
  1) 十五城全部重评:多边形口径 IoU/fp/fn + 带内(距边界<半格距)/带外误差分解,
     写回 e10x_*.json 的 metrics(附 metrics_v1 备查);
  2) 融合分类器留出选优(场源=非真值格样本):R0 多边形 / R1 场 / R2 并 / R3 交 /
     R4 带内多边形+带外场(150m 带);按十五城平均 IoU 选一条全局规则(不逐城挑),
     结果写 metrics.fusion。
"""
import bisect
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
from scipy.interpolate import griddata

from core import cache
from experiments.e4_sampling.run_e4 import grid_points, key
from experiments.maps.plot_maps import load_field
from experiments.paths import RESULTS

TH = 900
BAND = 150.0
CITIES = ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian",
          "chongqing", "changsha", "wuhan", "luoyang", "kunshan", "guilin",
          "zunyi", "yiwu", "nanchang", "huilongguan", "zhangjiang",
          "zhujiangxincheng", "yulin_cd", "qunli", "tianjin", "shenzhen",
          "kunming", "lanzhou", "xiamen", "shenyang", "qingdao",
          "suzhou", "changchun", "fuzhou"]
FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
RULES = ["R0多边形", "R1场", "R2并", "R3交", "R4带内多边形+带外场", "R2并+口袋"]


def eval_city(slug):
    sub, fname, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
    fp_ = os.path.join(RESULTS, sub, fname)
    d = json.load(open(fp_, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d[rk].items()}
    ks = sorted(radii)

    def r_at(brg):
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    def polar(p):
        dd = math.hypot((p[0] - center[0]) * 111320,
                        (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
        bb = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
        return dd, bb

    sp = d.get("metrics", {}).get("truth_spacing") or \
        (100 if slug in ("A",) else 250)
    half = 1050 if sp == 150 else 1000
    g = list(grid_points(center, sp, half))
    field = load_field(center)
    gkeys = {key(p) for p in g}
    src = [(k, v) for k, v in field.items() if k not in gkeys]
    z = None
    if len(src) >= 10:
        pts = np.array([k for k, _ in src])
        vals = np.array([v for _, v in src])
        z = griddata(pts, vals, np.array(g), method="linear")

    yt, poly, fld, band = [], [], [], []
    pockets = d.get("pockets") or []

    def pocket_in(p):
        dd, bb = polar(p)
        for pk in pockets:
            if abs(((bb - pk["bearing"] + 180) % 360) - 180) > (pk.get("wedge_deg") or 5):
                continue
            if isinstance(pk.get("gap"), list):          # v2 复通带:gap 外缘→第二边界
                if pk.get("outer") and pk["gap"][1] <= dd <= pk["outer"]:
                    return True
            elif pk.get("inner_m", 1e9) <= dd <= pk.get("outer_m", 0):
                return True
        return False

    pkin = [pocket_in(p) for p in g]
    inner_gaps = d.get("interior_gaps") or []

    def inner_hit(p):
        dd, bb = polar(p)
        for pk in inner_gaps:
            g2 = pk.get("gap") or []
            if len(g2) == 2 and g2[1] - g2[0] >= 20 and                abs(((bb - pk["bearing"] + 180) % 360) - 180) <= (pk.get("wedge_deg") or 1.2)                and g2[0] <= dd <= g2[1]:
                return True
        return False

    inner = [inner_hit(p) for p in g]
    for i, p in enumerate(g):
        row = cache.get(center, p)
        if not row:
            continue
        dd, bb = polar(p)
        r = r_at(bb)
        yt.append(row[0] <= TH)
        poly.append(dd < r)
        zv = z[i] if z is not None else None
        fld.append(zv is not None and not np.isnan(zv) and zv <= TH)
        band.append(abs(dd - r) <= BAND)

    def iou_of(pred):
        inter = sum(1 for a, b in zip(yt, pred) if a and b)
        union = sum(1 for a, b in zip(yt, pred) if a or b)
        return inter / max(1, union)

    fp_n = sum(1 for a, b in zip(yt, poly) if b and not a)
    fn_n = sum(1 for a, b in zip(yt, poly) if a and not b)
    oob = sum(1 for a, b, bd in zip(yt, poly, band) if a != b and not bd)
    preds = {
        "R0多边形": poly,
        "R1场": fld,
        "R2并": [a or b for a, b in zip(poly, fld)],
        "R3交": [a and b for a, b in zip(poly, fld)],
        "R4带内多边形+带外场": [pp if bd else ff
                                for pp, ff, bd in zip(poly, fld, band)],
        "R2并+口袋": [(a or b or pk) and not ih
                       for a, b, pk, ih in zip(poly, fld, pkin, inner)],
    }
    ious = {k: round(iou_of(v), 3) for k, v in preds.items()}
    return d, fp_, ious, fp_n, fn_n, oob, sp


def main():
    sums = {r: 0.0 for r in RULES}
    n = 0
    print(f"{'城':14s}" + "".join(f"{r:>10s}" for r in RULES) +
          f" {'FP':>3s} {'FN':>3s} {'带外':>4s}")
    rows = {}
    for slug in CITIES:
        label = {"A": "北京A·王府井", "B": "北京B·东花市"}.get(slug, slug)
        try:
            d, fp_, ious, fp_n, fn_n, oob, sp = eval_city(slug)
        except Exception as e:
            print(f"{slug:14s} 失败:{str(e)[:60]}")
            continue
        label = d.get("city", label)
        rows[slug] = (label, ious)
        for r in RULES:
            sums[r] += ious[r]
        n += 1
        print(f"{label:14s}" + "".join(f"{ious[r]:>10.3f}" for r in RULES) +
              f" {fp_n:>3d} {fn_n:>3d} {oob:>4d}")
        # 写回:metrics 修复 + 备查 v1 + 融合全表
        m = d.get("metrics", {})
        if "iou_v1" not in m:
            m["iou_v1"] = m.get("iou")
        m.update({"fp": fp_n, "fn": fn_n, "iou": ious["R0多边形"],
                  "out_band_errors": oob, "band_m": BAND,
                  "truth_spacing": m.get("truth_spacing") or sp})
        m["fusion"] = ious
        d["metrics"] = m
        json.dump(d, open(fp_, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    best = max(RULES, key=lambda r: sums[r])
    print(f"\n十五城平均:" + "".join(f"{sums[r]/n:>10.3f}" for r in RULES))
    print(f"全局最优规则:{best}(平均 {sums[best]/n:.3f})")


if __name__ == "__main__":
    main()
