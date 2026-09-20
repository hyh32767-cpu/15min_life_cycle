"""E10 · 极端边界问题定量分析 + 对策离线模拟(零 API)

用户关切:±15m 二分精度 ≠ 边界形状保真。墙/河造成的:
  ① 弦幻影:16 边形弦切过障碍 → 圈内假阳性(幻影覆盖)
  ② 孤岛:多边形内实际 >15min 的不可达口袋
  ③ 非单调射线:一条射线上 T 多次穿越 900s(障碍后又有可达区)

分析(全部基于缓存场):
  A. 幻影覆盖统计:50m 格点上 in_polygon vs 实测的 FP/FN,按方位扇区聚类
  B. 对策模拟 1:弦中点验证 + 角度自适应加密(迭代插入射线直到弦一致)
  C. 对策模拟 2:内部随机探针(孤岛抽检)
  D. 非单调点地图(E2 数据复用)
产出:experiments/results/e10_barrier.json
"""
import bisect
import json
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.coord import dest_at
from experiments.e4_sampling.analyze_e4 import load_cache_field, replay_bisect
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, idw, key

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900


def main():
    setup = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"), encoding="utf-8"))
    center = tuple(setup["center"])
    field = load_cache_field(center)
    lat50 = [tuple(v) for v in setup["lat50"]]
    truth50 = setup["truth50"]

    def polar(p):
        d = math.hypot((p[0] - center[0]) * 111320,
                       (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
        b = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
        return d, b

    def actual(p):
        return idw(field, [p])[0]

    # ---------- A. 幻影覆盖(弦切障碍)统计 ----------
    b16 = [i * 22.5 for i in range(16)]
    r16, _ = replay_bisect(field, center, b16)

    def r_at(brg, radii):
        ks = sorted(radii)
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    def in_poly(p, radii, margin=1.0):
        d, b = polar(p)
        return d < margin * r_at(b, radii)

    fp_sectors, fn_sectors = {}, {}
    fp_total = fn_total = 0
    for p, truth in zip(lat50, truth50):
        pred = in_poly(p, r16)
        d, b = polar(p)
        sector = int(b // 22.5) * 22.5
        if pred and not truth:
            fp_total += 1
            fp_sectors[sector] = fp_sectors.get(sector, 0) + 1
        if truth and not pred:
            fn_total += 1
            fn_sectors[sector] = fn_sectors.get(sector, 0) + 1
    n_in = sum(truth50)
    print("== A. 16 边形幻影覆盖(50m 格点,n=761)==")
    print(f"  假阳性(多边形说圈内、实测>15min):{fp_total} 格 | 假阴性:{fn_total} 格")
    print(f"  FP 聚类扇区(方位°→格数):{dict(sorted(fp_sectors.items(), key=lambda kv: -kv[1])[:6])}")
    print(f"  FN 聚类扇区:{dict(sorted(fn_sectors.items(), key=lambda kv: -kv[1])[:6])}")

    # ---------- B. 对策 1:弦中点验证 + 自适应加密模拟 ----------
    print("\n== B. 弦中点验证 + 角度加密模拟 ==")
    radii = dict(r16)
    cost_probe = 0
    for round_i in range(3):
        bad = []
        ks = sorted(radii)
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            mid_b = ((a + b) / 2) % 360
            gap = (b - a)
            r_here = r_at(mid_b, radii)
            probe = dest_at(center[1], center[0], mid_b, r_here * 0.97)
            cost_probe += 1
            t = actual(probe)
            if t is not None and t > TH:
                bad.append((mid_b, gap, r_here, t))
        if not bad:
            print(f"  第 {round_i+1} 轮:全部弦中点一致 ✓(累计探针 {cost_probe} 个)")
            break
        print(f"  第 {round_i+1} 轮:{len(bad)} 条弦中点违规(探针累计 {cost_probe}):")
        for mb, gap, rr, t in bad:
            print(f"    方位 {mb:6.1f}° 弦跨 {gap:4.1f}° 边界r={rr:5.0f}m 实测 {t:5.0f}s")
        new_radii, _ = replay_bisect(field, center, [mb for mb, *_ in bad])
        radii.update(new_radii)
        print(f"    → 插入 {len(bad)} 条射线重二分(在线成本 ≈ {len(bad)}×8 对)")
    else:
        print(f"  3 轮后仍有违规,标记复杂扇区")

    # 加密后复评
    fp2 = fn2 = 0
    for p, truth in zip(lat50, truth50):
        pred = in_poly(p, radii)
        if pred and not truth:
            fp2 += 1
        if truth and not pred:
            fn2 += 1
    yt = truth50
    yp = [in_poly(p, radii) for p in lat50]
    inter = sum(1 for a, b in zip(yt, yp) if a and b)
    union = sum(1 for a, b in zip(yt, yp) if a or b)
    print(f"  加密后:FP {fp_total}→{fp2},FN {fn_total}→{fn2},IoU {inter/union:.3f},"
          f"射线数 16→{len(radii)}")

    # ---------- C. 对策 2:内部随机探针(孤岛抽检)----------
    print("\n== C. 内部孤岛抽检(K=30)==")
    rng = random.Random(7)
    probes, islands = 0, []
    while probes < 30:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        d, b = polar(p)
        if d < 0.8 * r_at(b, radii):
            probes += 1
            t = actual(p)
            if t is not None and t > TH:
                islands.append((round(b), round(d), round(t)))
    print(f"  探针 {probes} 个:孤岛/凹陷命中 {len(islands)} 个 {islands if islands else ''}")

    # ---------- D. 非单调点地图(E2)----------
    e2 = json.load(open(os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e2.json"),
                        encoding="utf-8"))
    viols = []
    for brg, v in e2["rays"].items():
        for x in v["violations"]:
            viols.append({"bearing": int(brg), "dist_m": x["dist_m"],
                          "prev_s": x["prev_s"], "cur_s": x["cur_s"]})
    print(f"\n== D. E2 非单调点(墙/河签名)==: {len(viols)} 个")
    for x in viols:
        print(f"  {x['bearing']:3d}° @ {x['dist_m']}m: {x['prev_s']}s → {x['cur_s']}s")

    json.dump({"fp_total_16gon": fp_total, "fn_total_16gon": fn_total,
               "fp_sectors": {str(k): v for k, v in fp_sectors.items()},
               "after_refine": {"fp": fp2, "fn": fn2, "rays": len(radii),
                                "probes_chord": cost_probe, "iou": round(inter/union, 3)},
               "islands_found": islands, "non_monotonic": viols,
               "refined_radii": {f"{b:.1f}": round(r, 1) for b, r in sorted(radii.items())}},
              open(os.path.join(_ROOT, "experiments", "results", "e10_boundary", "e10_barrier.json"),
                   "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/e10_barrier.json")


if __name__ == "__main__":
    main()
