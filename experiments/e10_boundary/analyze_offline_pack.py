# -*- coding: utf-8 -*-
"""OFFPK · 零成本离线分析包(2026-08-31)

A1 多阈值等时线重放:哈/昆/桂三城(最难/最易/最各向异性),TH=300/600/900/1200s
   从缓存阶梯逐向重放首穿越 → 四层嵌套轮廓一张图(证明方法对任意时长成立)。
A2 绕行系数 ρ 十五城汇总:e10x_*.json 的 rho.median/tau(A/B 缺则标 —)。
A3 规模-难度回归:十五城 aniso / 收敛向数 k / pairs_used vs 城市规模档散点。
产出:results/maps/multi_threshold_*.png、size_difficulty.png + docs/14 数据节。
"""
import bisect
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from core.coord import dest_at
from experiments.e4_sampling.run_e4 import key
from experiments.maps.plot_maps import load_field, to_wgs
from experiments.paths import RESULTS

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

RES10 = os.path.join(RESULTS, "e10_boundary")
TIER = {"北京A": "直辖市核心", "北京B": "直辖市核心", "上海": "直辖市核心",
        "广州": "省会", "成都": "省会", "哈尔滨": "省会", "西安": "省会",
        "长沙": "省会", "武汉": "省会", "重庆": "直辖市核心",
        "洛阳": "地级市", "遵义": "地级市", "桂林": "地级市",
        "昆山": "县级市", "义乌": "县级市"}
FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}


def load(slug):
    sub, fn, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
    d = json.load(open(os.path.join(RESULTS, sub, fn), encoding="utf-8"))
    return d, {float(k): v for k, v in d[rk].items()}, tuple(d["center"])


def ladder_radii(field, center, radii, th):
    """给定阈值,从缓存阶梯逐向重放首穿越半径(±1.2° 归并)。"""
    kcos = math.cos(math.radians(center[0]))
    by = {}
    for p, t in field.items():
        dd = math.hypot((p[0] - center[0]) * 111320,
                        (p[1] - center[1]) * 111320 * kcos)
        bb = math.degrees(math.atan2((p[1] - center[1]) * 111320 * kcos,
                                     (p[0] - center[0]) * 111320)) % 360
        nb = min(radii, key=lambda x: min(abs(x - bb), 360 - abs(x - bb)))
        if min(abs(nb - bb), 360 - abs(nb - bb)) <= 1.2:
            by.setdefault(nb, []).append((dd, t))
    out = {}
    for b, seq in by.items():
        seq.sort()
        ok_d = 0
        for dd, t in seq:
            if t <= th:
                ok_d = max(ok_d, dd)
            else:
                break
        if ok_d > 0:
            out[b] = ok_d
    return out


def a1_multithreshold():
    for slug, tag in [("harbin", "最难(k=42)"), ("kunshan", "最易(k=23)"),
                      ("guilin", "最各向异性(4.62)")]:
        d, radii, center = load(slug)
        field = load_field(center)
        fig, ax = plt.subplots(figsize=(8, 8), dpi=200)
        clat, clng = to_wgs(center)
        colors = {300: "#2ca02c", 600: "#1f77b4", 900: "#d62728", 1200: "#9467bd"}
        for th in (300, 600, 900, 1200):
            rr = ladder_radii(field, center, radii, th)
            if len(rr) < 4:
                continue
            ks = sorted(rr)
            xs, ys = [], []
            for i in range(0, 361, 2):
                b = i % 360
                j = bisect.bisect_right(ks, b) - 1
                b0, b1 = ks[j % len(ks)], ks[(j + 1) % len(ks)]
                db = (b1 - b0) % 360 or 360
                t = ((b - b0) % 360) / db
                r = rr[b0] * (1 - t) + rr[b1] * t
                p = dest_at(center[1], center[0], b, r)
                la, ln = to_wgs(p)
                xs.append(ln)
                ys.append(la)
            ax.plot(xs, ys, color=colors[th], lw=1.8,
                    label=f"{th//60} min({len(rr)}向)")
        ax.plot(clng, clat, "k*", ms=14)
        ax.set_aspect(1 / math.cos(math.radians(clat)))
        ax.set_title(f"{d['city']} · 多阈值等时线(缓存重放,零API)· {tag}")
        ax.legend(loc="upper right", fontsize=9)
        out = os.path.join(RESULTS, "maps", f"multi_threshold_{slug}.png")
        fig.savefig(out, dpi=200, bbox_inches="tight")
        plt.close(fig)
        print(f"[A1] {out}")


def a2_rho():
    rows = []
    for slug in ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian",
                 "chongqing", "changsha", "wuhan", "luoyang", "kunshan",
                 "guilin", "zunyi", "yiwu"]:
        d, _, _ = load(slug)
        rho = d.get("rho") or {}
        rows.append((d.get("city", slug), rho.get("median"), rho.get("tau_p75")))
    print("[A2] ρ 十五城:")
    for c, m, t in rows:
        print(f"  {c:10s} median={m if m is not None else '—'} tau_p75={t if t is not None else '—'}")
    return rows


def a3_regression():
    pts = {"直辖市核心": ([], []), "省会": ([], []), "地级市": ([], []), "县级市": ([], [])}
    kp = {"直辖市核心": ([], []), "省会": ([], []), "地级市": ([], []), "县级市": ([], [])}
    for slug in ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian",
                 "chongqing", "changsha", "wuhan", "luoyang", "kunshan",
                 "guilin", "zunyi", "yiwu"]:
        d, radii, _ = load(slug)
        name = d.get("city") or d.get("community") or slug
        prefix = name.split("·")[0] if "·" in name else ("北京A" if slug == "A"
                                                         else "北京B" if slug == "B" else name)
        tier = TIER.get(prefix) or TIER.get(name, "省会")
        aniso = d.get("anisotropy") or round(max(radii.values()) / max(1e-9, min(radii.values())), 2)
        pairs = d.get("pairs_used") or d.get("metrics", {}).get("pairs_used")
        if pairs is None:
            continue
        pts[tier][0].append(aniso)
        pts[tier][1].append(pairs)
        kp[tier][0].append(len(radii))
        kp[tier][1].append(pairs)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=200)
    mk = {"直辖市核心": "o", "省会": "s", "地级市": "^", "县级市": "D"}
    for tier, (xs, ys) in pts.items():
        axes[0].scatter(xs, ys, marker=mk[tier], s=70, label=tier)
        axes[1].scatter(kp[tier][0], kp[tier][1], marker=mk[tier], s=70, label=tier)
    for ax, xl, t in [(axes[0], "各向异性 max/min", "各向异性 vs 总调用对数"),
                      (axes[1], "收敛向数 k", "收敛向数 vs 总调用对数")]:
        ax.set_xlabel(xl)
        ax.set_ylabel("该城总调用对数")
        ax.set_title(t)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    out = os.path.join(RESULTS, "maps", "size_difficulty.png")
    fig.savefig(out, dpi=200, bbox_inches="tight")
    print(f"[A3] {out}")


if __name__ == "__main__":
    a1_multithreshold()
    a2_rho()
    a3_regression()
