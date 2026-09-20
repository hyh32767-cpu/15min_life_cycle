# -*- coding: utf-8 -*-
"""COST · 8向+v3加密 与 16起步成品 的逐城对数对照(2026-09-01,零 API)

口径:对数 = 每向 ±1.2° 归并后的缓存阶梯探针数(该向真实二分成本);
     16 起步 = e10x 成品向的阶梯计数;8向 = 均匀8向阶梯 + v3 加密新增向阶梯。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.maps.plot_maps import load_field
from experiments.paths import RESULTS

TH = 900
FILES = {"A": ("e4_sampling", "e4.json"), "B": ("e4_sampling", "e4b.json")}
SLUGS = ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian", "chongqing",
         "changsha", "wuhan", "luoyang", "kunshan", "guilin", "zunyi", "yiwu",
         "nanchang", "huilongguan", "zhangjiang", "zhujiangxincheng", "yulin_cd"]


def analyze(slug):
    sub, fn = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json"))
    d = json.load(open(os.path.join(RESULTS, sub, fn), encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    field = load_field(center)
    kcos = math.cos(math.radians(center[0]))
    pts = []
    for p, t in field.items():
        dd = math.hypot((p[0] - center[0]) * 111320,
                        (p[1] - center[1]) * 111320 * kcos)
        bb = math.degrees(math.atan2((p[1] - center[1]) * 111320 * kcos,
                                     (p[0] - center[0]) * 111320)) % 360
        pts.append((bb, dd, t))

    def ang_close(a, b):
        return min(abs(a - b) % 360, 360 - (abs(a - b)) % 360)

    def ladder_cost(rr):
        return sum(sum(1 for bb, _, _ in pts if ang_close(bb, b) <= 1.2)
                   for b in rr)

    def r_at(rr, brg):
        ks = sorted(rr)
        i = 0
        for j in range(len(ks)):
            if ks[j] <= brg:
                i = j
        b0, b1 = ks[i], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return rr[b0] * (1 - t) + rr[b1] * t

    def chord_len(b0, b1, r0, r1):
        x0, y0 = r0 * math.sin(math.radians(b0)), r0 * math.cos(math.radians(b0))
        x1, y1 = r1 * math.sin(math.radians(b1)), r1 * math.cos(math.radians(b1))
        return math.hypot(x1 - x0, y1 - y0)

    # 8 向起步(重放)
    r8 = {}
    for i in range(8):
        seq = sorted((dd, t) for bb, dd, t in pts
                     if ang_close(bb, i * 45.0) <= 1.2)
        ok = 0.0
        for dd, t in seq:
            if t <= TH:
                ok = max(ok, dd)
            else:
                r8[i * 45.0] = (ok + dd) / 2
                break
    # v3 加密(与 plot_maps 触发器一致)
    ev = [(bb, dd) for bb, _, t in pts if t > TH]
    for _ in range(12):
        ks = sorted(r8)
        ins = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            a0 = a % 360
            arc = (b - a) % 360 or 360
            mb0 = ((a + b) / 2) % 360
            viol = any(((bb - a0) % 360) < arc and dd < r_at(r8, bb)
                       for bb, dd in ev)
            long_chord = chord_len(a0, b % 360, r8[a0], r8[b % 360]) > 200
            lowbias = abs(r_at(r8, mb0) - r_at(radii, mb0)) > 60
            if viol or long_chord or lowbias:
                cands = [bb for bb in radii if bb not in r8 and ((bb - a0) % 360) < arc]
                if cands:
                    ins.append(cands[len(cands) // 2])
        if not ins:
            break
        for bb in ins:
            r8[bb] = radii[bb]

    return d, radii, r8, pts


def main():
    print(f"{'城':14s} {'成品k':>5s} {'8+v3k':>6s} {'8+v3对数':>8s} "
          f"{'16起步对数':>9s} {'节省':>6s}")
    tot8 = tot16 = n = 0
    worse = []
    for slug in SLUGS:
        d, radii, r8, pts = analyze(slug)

        def cost(rr):
            return sum(sum(1 for bb, _, _ in pts
                           if min(abs(bb - b) % 360, 360 - (abs(bb - b)) % 360) <= 1.2)
                       for b in rr)

        name = d.get("city") or d.get("community") or slug
        c8, c16 = cost(r8), d.get("pairs_used") or cost(radii)
        save = (1 - c8 / max(1, c16)) * 100
        flag = " ⚠️" if c8 > c16 else ""
        print(f"{name:14s} {len(radii):5d} {len(r8):6d} {c8:8d} {c16:9d} {save:+5.0f}%{flag}")
        tot8 += c8
        tot16 += c16
        n += 1
        if c8 > c16:
            worse.append(name)
    print(f"\n合计:8向+v3加密 {tot8} 对 vs 16起步成品 {tot16} 对 "
          f"→ 省 {(1 - tot8 / max(1, tot16)) * 100:.0f}%({n} 社区)")
    print("反超城市:", worse if worse else "无")


if __name__ == "__main__":
    main()
