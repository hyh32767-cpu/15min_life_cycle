"""E4N · 新增四大城市市中心社区:E10 管线 + 200m 真值 + 50m 网格(在线)

对象:西安·钟楼(明城墙环障)/ 重庆·解放碑(立体过街)/ 长沙·五一广场 / 武汉·江汉路
每城流程(预算 ≤1000 对/城,全局 ≤2200,触顶优雅停止):
  16 向二分(tol15)→ 弦差复杂度信号(≥2 条>200m 补 32 向)
  → mid 探针 ≤3 轮(违规方位重二分)→ ρ 探针(≤24 弦)→ 孤岛抽检 K=15
  → 200m 真值格点(±1km)→ 50m 网格(±500m)
产出:experiments/results/e10x_{slug}.json(与既有格式兼容,直接进地图管线)
"""
import json
import math
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at
from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
WALK_MS = 1.083
GLOBAL_CAP = 999999               # 按用户指示:不考虑配额,跑到收敛/跑完
NEW_CITIES = [
    ("xian", "西安市碑林区钟楼", "西安·钟楼", "明城墙环障"),
    ("chongqing", "重庆市渝中区解放碑步行街", "重庆·解放碑", "立体过街/山城"),
    ("changsha", "长沙市芙蓉区五一广场", "长沙·五一广场", "商圈规则+湘江"),
    ("wuhan", "武汉市江汉区江汉路步行街", "武汉·江汉路", "老城+长江"),
]


def g_used(eids):
    db = os.path.join(ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id IN "
                         f"({','.join('?' * len(eids))})", eids).fetchone()[0]


def run_city(idx, slug, addr, label, ctype):
    eid = f"E4N{idx}"
    r = bc.geocode(addr, experiment_id=eid)
    if not r.ok:
        print(f"[{label}] geocode 失败:{r.message}")
        return False
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    print(f"\n===== {label}({ctype})===== 中心 {center[0]:.5f},{center[1]:.5f}")
    R = CityRunner(eid, center, cap=999999)
    b16 = [i * 22.5 for i in range(16)]
    radii = R.bisect(b16)
    print(f"16 向二分({R.used()} 对);半径 {min(radii.values()):.0f}-{max(radii.values()):.0f}m")
    gaps = []
    for a, b in zip(b16, b16[1:] + [b16[0] + 360]):
        gaps.append(abs(radii[a % 360] - radii[b % 360]))
    if sum(1 for g in gaps if g > 200) >= 2 and R.left() > 200:
        print("  复杂信号 → 补满 32 向")
        radii.update(R.bisect([b + 11.25 for b in b16]))
    aniso = max(radii.values()) / max(1e-9, min(radii.values()))

    chord_viol, mid_probes = [], 0
    for rd in range(3):
        ks = sorted(radii)
        bad = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            mb = ((a + b) / 2) % 360
            probe = R.endpoint(mb, R.r_at(mb, radii) * 0.97)
            R.measure([probe])
            mid_probes += 1
            t = R.t_of(probe)
            if t is not None and t > TH:
                bad.append(mb)
                chord_viol.append(round(mb, 1))
        if not bad:
            print(f"  mid 第{rd+1}轮一致 ✓(探针累计 {mid_probes})")
            break
        print(f"  mid 第{rd+1}轮:{len(bad)} 弦违规 {['%.1f°' % x for x in bad]}")
        radii.update(R.bisect(bad))

    rho_rows = []
    ks = sorted(radii)
    for a, b in list(zip(ks, ks[1:] + [ks[0] + 360]))[:24]:
        p1 = R.endpoint(a % 360, radii[a % 360])
        p2 = R.endpoint(b % 360, radii[b % 360])
        straight = math.hypot((p1[0] - p2[0]) * 111320,
                              (p1[1] - p2[1]) * 111320 * math.cos(math.radians(p1[0])))
        rr = bc.direction("walking", p1, p2, experiment_id=eid)
        t = rr.duration_s if rr.ok else None
        rho_rows.append({"chord": round(((a + b) / 2) % 360, 1),
                         "rho": round(t / (straight / WALK_MS), 2) if t else None})
        time.sleep(0.4)
    rhos = sorted(x["rho"] for x in rho_rows if x["rho"])
    tau = rhos[int(0.75 * len(rhos))] if rhos else None
    hot = [x["chord"] for x in rho_rows if x["rho"] and tau and x["rho"] > max(tau, 1.8)]

    rng = random.Random(11)
    islands, probes_n = [], 0
    while probes_n < 15 and R.left() > 160:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        d, b = R.polar(p)
        if d < 0.8 * R.r_at(b, radii):
            R.measure([p])
            probes_n += 1
            t = R.t_of(p)
            if t is not None and t > TH:
                islands.append({"bearing": round(b), "dist_m": round(d), "t_s": round(t)})

    # 200m 真值
    m = {}
    if R.left() >= 121:
        g = grid_points(center, 200, 1000)
        R.measure(g)
        truth = {key(p): (R.cached(p) or (None, None))[0] for p in g}
        truth = {k: v for k, v in truth.items() if v is not None}
        keys = list(truth)
        yt = [truth[k] <= TH for k in keys]
        yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
        inter = sum(1 for a, b2 in zip(yt, yp) if a and b2)
        union = sum(1 for a, b2 in zip(yt, yp) if a or b2)
        m = {"fp": sum(1 for a, b2 in zip(yt, yp) if b2 and not a),
             "fn": sum(1 for a, b2 in zip(yt, yp) if a and not b2),
             "iou": round(inter / max(1, union), 3), "truth_n": len(keys),
             "truth_spacing": 200}
        print(f"  200m 真值:FP={m['fp']} FN={m['fn']} IoU={m['iou']}(n={m['truth_n']})")

    # 50m 网格(剩余预算决定覆盖)
    n50 = 0
    if R.left() > 50:
        g50 = grid_points(center, 50, 500)
        todo = [p for p in g50 if R.cached(p) is None]
        n50_target = min(len(todo), R.left())
        R.measure(todo[:n50_target])
        n50 = sum(1 for p in g50 if R.cached(p) is not None)
        print(f"  50m 网格覆盖 {n50}/{len(g50)}")

    out = {"city": label, "type": ctype, "center": list(center), "eid": eid,
           "pairs_used": R.used(), "rays": len(radii), "anisotropy": round(aniso, 2),
           "radius_range": [round(min(radii.values())), round(max(radii.values()))],
           "gap_over_200m": sum(1 for g in gaps if g > 200),
           "chord_violations": chord_viol, "mid_probes": mid_probes,
           "rho": {"median": rhos[len(rhos) // 2] if rhos else None,
                   "tau_p75": tau, "hot_chords": hot},
           "islands": islands, "metrics": m,
           "grid50_covered": n50,
           "radii": {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}}
    json.dump(out, open(os.path.join(ROOT, "experiments", "results", "e10_boundary", f"e10x_{slug}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  完成:射线{len(radii)} 各向异性{aniso:.2f} 弦违规{len(chord_viol)} "
          f"孤岛{len(islands)} | 共 {R.used()} 对")
    return True


def main():
    eids = [f"E4N{i}" for i in range(len(NEW_CITIES))]
    for i, (slug, addr, label, ctype) in enumerate(NEW_CITIES):
        if g_used(eids) >= GLOBAL_CAP:
            print(f"[{label}] 全局预算触顶({g_used(eids)}/{GLOBAL_CAP}),停止")
            break
        try:
            run_city(i, slug, addr, label, ctype)
        except Exception as e:
            print(f"[{label}] 失败:{str(e)[:150]}")
    print(f"\n本批总消耗 {g_used(eids)} 对")


if __name__ == "__main__":
    main()
