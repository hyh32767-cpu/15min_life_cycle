# -*- coding: utf-8 -*-
"""D5 · 同城异区五社区(2026-09-01):检验"方法是否只会画市中心"

对象(同城区类型对照,每城已有一市中心社区):
  回龙观(北京·超大型居住区)/ 张江(上海·科技园)/ 珠江新城(广州·新CBD)/
  玉林(成都·老居住市井)/ 群力(哈尔滨·新区)
流程与 run_small5 相同:16向(tol15)→复杂信号补32→mid 违规清零(截断≠成功)
→ρ 24弦→孤岛15→250m 真值。产出 e10x_{slug}.json。EID=D5{i}。可带 slug 参数续跑。
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
from experiments.e4_sampling.run_e4 import grid_points, key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
WALK_MS = 1.083
CAP_PER_CITY = 450
GLOBAL_CAP = 3500   # 2026-09-02 新额度
CITIES = [
    ("huilongguan", "北京市昌平区回龙观地铁站", "北京·回龙观", "超大型居住区"),
    ("zhangjiang", "上海市浦东新区张江地铁站", "上海·张江", "科技园区"),
    ("zhujiangxincheng", "广州市天河区珠江新城地铁站", "广州·珠江新城", "新CBD"),
    ("yulin_cd", "成都市武侯区玉林东路", "成都·玉林", "老居住市井"),
    ("qunli", "哈尔滨市道里区群力中心广场", "哈尔滨·群力", "新区"),
]


def used(eids):
    db = os.path.join(ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id IN "
                         f"({','.join('?' * len(eids))})", eids).fetchone()[0]


def run_city(idx, slug, addr, label, ctype):
    eid = f"D5{idx}"
    r = None
    for attempt in range(6):
        r = bc.geocode(addr, experiment_id=eid)
        if r.ok:
            break
        print(f"[{label}] geocode 第{attempt+1}次失败:{str(r.message)[:60]},15s 后重试")
        time.sleep(15)
    if not r.ok:
        print(f"[{label}] geocode 最终失败,跳过")
        return False
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    print(f"\n===== {label}({ctype})===== 中心 {center[0]:.5f},{center[1]:.5f}")
    R = CityRunner(eid, center, cap=CAP_PER_CITY)
    b16 = [i * 22.5 for i in range(16)]
    radii = R.bisect(b16, tol=15.0)
    print(f"16 向二分({R.used()} 对);半径 {min(radii.values()):.0f}-{max(radii.values()):.0f}m")
    gaps = [abs(radii[a % 360] - radii[b % 360])
            for a, b in zip(b16, b16[1:] + [b16[0] + 360])]
    if sum(1 for g in gaps if g > 200) >= 2 and R.left() > 200:
        print("  复杂信号 → 补满 32 向")
        radii.update(R.bisect([b + 11.25 for b in b16], tol=15.0))
    aniso = max(radii.values()) / max(1e-9, min(radii.values()))

    chord_viol, mid_probes, cleared = [], 0, False
    new_bearings = None
    for rd in range(6):
        ks = sorted(radii)
        chords = list(zip(ks, ks[1:] + [ks[0] + 360]))
        if new_bearings is not None:
            chords = [(a, b) for a, b in chords
                      if any(abs(((a + b) / 2) % 360 - nb) < 1e-6 for nb in new_bearings)]
        bad, truncated = [], False
        for a, b in chords:
            mb = ((a + b) / 2) % 360
            probe = R.endpoint(mb, R.r_at(mb, radii) * 0.97)
            R.measure([probe])
            if R.left() <= 0:
                truncated = True
                break
            mid_probes += 1
            t = R.t_of(probe)
            if t is not None and t > TH:
                bad.append(mb)
                chord_viol.append(round(mb, 1))
        if truncated:
            print(f"  mid 第{rd+1}轮预算截断,如实记未清零")
            break
        if not bad:
            print(f"  mid 第{rd+1}轮一致 ✓(累计探针 {mid_probes})")
            cleared = True
            break
        print(f"  mid 第{rd+1}轮:{len(bad)} 弦违规 {['%.1f°' % x for x in bad]}")
        new_rays = R.bisect(bad, tol=25.0)
        radii.update(new_rays)
        new_bearings = bad
        if R.left() <= 0:
            break

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
        time.sleep(0.3)
    rhos = sorted(x["rho"] for x in rho_rows if x["rho"])
    tau = rhos[int(0.75 * len(rhos))] if rhos else None
    hot = [x["chord"] for x in rho_rows if x["rho"] and tau and x["rho"] > max(tau, 1.8)]

    rng = random.Random(11)
    islands, probes_n = [], 0
    while probes_n < 15 and R.left() > 40:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        d, b = R.polar(p)
        if d < 0.8 * R.r_at(b, radii):
            R.measure([p])
            probes_n += 1
            t = R.t_of(p)
            if t is not None and t > TH:
                islands.append({"bearing": round(b), "dist_m": round(d), "t_s": round(t)})

    m = {}
    g = grid_points(center, 250, 1000)
    R.measure(g)
    truth = {}
    for p in g:
        row = R.cached(p)
        if row:
            truth[key(p)] = row[0]
    truth = {k: v for k, v in truth.items() if v is not None}
    keys = list(truth)
    yt = [truth[k] <= TH for k in keys]
    yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
    inter = sum(1 for a, b2 in zip(yt, yp) if a and b2)
    union = sum(1 for a, b2 in zip(yt, yp) if a or b2)
    m = {"fp": sum(1 for a, b2 in zip(yt, yp) if b2 and not a),
         "fn": sum(1 for a, b2 in zip(yt, yp) if a and not b2),
         "iou": round(inter / max(1, union), 3), "truth_n": len(keys),
         "truth_spacing": 250}

    out = {"city": label, "type": ctype, "center": list(center), "eid": eid,
           "pairs_used": R.used(), "rays": len(radii), "anisotropy": round(aniso, 2),
           "radius_range": [round(min(radii.values())), round(max(radii.values()))],
           "gap_over_200m": sum(1 for g2 in gaps if g2 > 200),
           "chord_violations": chord_viol, "mid_probes": mid_probes,
           "mid_cleared": cleared,
           "rho": {"median": rhos[len(rhos) // 2] if rhos else None,
                   "tau_p75": tau, "hot_chords": hot},
           "islands": islands, "metrics": m,
           "radii": {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}}
    json.dump(out, open(os.path.join(ROOT, "experiments", "results", "e10_boundary",
                                     f"e10x_{slug}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  250m 真值 IoU={m['iou']}(n={m['truth_n']}) | 完成:{len(radii)}向 "
          f"清零={cleared} 孤岛{len(islands)} | 共 {R.used()} 对")
    return True


def main():
    only = set(sys.argv[1:])
    eids = [f"D5{i}" for i in range(len(CITIES))]
    for i, (slug, addr, label, ctype) in enumerate(CITIES):
        if only and slug not in only:
            continue
        if used(eids) >= GLOBAL_CAP:
            print(f"[{label}] 全局预算触顶({used(eids)}/{GLOBAL_CAP}),停止")
            break
        try:
            run_city(i, slug, addr, label, ctype)
        except Exception as e:
            print(f"[{label}] 失败:{str(e)[:150]}")
    print(f"\nD5 总消耗 {used(eids)} 对")


if __name__ == "__main__":
    main()
