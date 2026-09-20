# -*- coding: utf-8 -*-
"""N6 · 新增五城(2026-09-03):东北老工业/海滨/古城/计划经济/沿海历史街区"""
import json, math, os, random, sqlite3, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core import baidu_client as bc
from core.coord import dest_at
from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.e4_sampling.run_e4 import grid_points, key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
WALK_MS = 1.083
CAP_PER_CITY = 600
GLOBAL_CAP = 2800
CITIES = [
    ("shenyang", "沈阳市沈河区中街步行街", "沈阳·中街", "东北老工业商圈"),
    ("qingdao", "青岛市市南区栈桥", "青岛·栈桥", "海滨旅游城市"),
    ("suzhou", "苏州市姑苏区观前街", "苏州·观前街", "古城园林街区"),
    ("changchun", "长春市朝阳区重庆路", "长春·重庆路", "计划经济商业区"),
    ("fuzhou", "福州市鼓楼区三坊七巷", "福州·三坊七巷", "沿海历史街区"),
]

def used(eids):
    db = os.path.join(ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id IN "
                         f"({','.join('?' * len(eids))})", eids).fetchone()[0]

def run_city(idx, slug, addr, label, ctype):
    eid = f"N6{idx}"
    r = None
    for attempt in range(6):
        r = bc.geocode(addr, experiment_id=eid)
        if r.ok: break
        print(f"[{label}] geocode retry {attempt+1}", flush=True)
        time.sleep(15)
    if not r.ok:
        print(f"[{label}] geocode FAIL", flush=True); return False
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    print(f"\n===== {label}({ctype})===== {center[0]:.5f},{center[1]:.5f}", flush=True)
    R = CityRunner(eid, center, cap=CAP_PER_CITY)
    b16 = [i * 22.5 for i in range(16)]
    radii = R.bisect(b16, tol=15.0)
    print(f"16向({R.used()}对) 半径{min(radii.values()):.0f}-{max(radii.values()):.0f}m", flush=True)
    gaps = [abs(radii[a%360]-radii[b%360]) for a, b in zip(b16, b16[1:]+[b16[0]+360])]
    if sum(1 for g in gaps if g > 200) >= 2 and R.left() > 200:
        print("  复杂→补32向", flush=True)
        radii.update(R.bisect([b + 11.25 for b in b16], tol=15.0))
    aniso = max(radii.values()) / max(1e-9, min(radii.values()))
    chord_viol, mid_probes, cleared = [], 0, False
    new_b = None
    for rd in range(6):
        ks = sorted(radii)
        chords = list(zip(ks, ks[1:]+[ks[0]+360]))
        if new_b is not None:
            chords = [(a, b) for a, b in chords if any(abs(((a+b)/2)%360 - nb) < 1e-6 for nb in new_b)]
        bad, trunc = [], False
        for a, b in chords:
            mb = ((a + b) / 2) % 360
            probe = R.endpoint(mb, R.r_at(mb, radii) * 0.97)
            R.measure([probe])
            if R.left() <= 0: trunc = True; break
            mid_probes += 1
            t = R.t_of(probe)
            if t is not None and t > TH:
                bad.append(mb); chord_viol.append(round(mb, 1))
        if trunc: print(f"  mid r{rd+1} 截断", flush=True); break
        if not bad:
            print(f"  mid r{rd+1} ✓({mid_probes}探针)", flush=True); cleared = True; break
        print(f"  mid r{rd+1}:{len(bad)}违规", flush=True)
        radii.update(R.bisect(bad, tol=25.0))
        new_b = bad
        if R.left() <= 0: break
    rho_rows = []
    ks = sorted(radii)
    for a, b in list(zip(ks, ks[1:]+[ks[0]+360]))[:24]:
        p1 = R.endpoint(a%360, radii[a%360]); p2 = R.endpoint(b%360, radii[b%360])
        st = math.hypot((p1[0]-p2[0])*111320, (p1[1]-p2[1])*111320*math.cos(math.radians(p1[0])))
        rr = bc.direction("walking", p1, p2, experiment_id=eid)
        t = rr.duration_s if rr.ok else None
        rho_rows.append({"chord": round(((a+b)/2)%360,1), "rho": round(t/(st/WALK_MS),2) if t else None})
        time.sleep(0.3)
    rhos = sorted(x["rho"] for x in rho_rows if x["rho"])
    tau = rhos[int(0.75*len(rhos))] if rhos else None
    hot = [x["chord"] for x in rho_rows if x["rho"] and tau and x["rho"] > max(tau,1.8)]
    rng = random.Random(11)
    islands, pn = [], 0
    while pn < 15 and R.left() > 40:
        p = dest_at(center[1], center[0], rng.uniform(0,360), rng.uniform(150,900))
        d, b = R.polar(p)
        if d < 0.8 * R.r_at(b, radii):
            R.measure([p]); pn += 1
            t = R.t_of(p)
            if t is not None and t > TH:
                islands.append({"bearing": round(b), "dist_m": round(d), "t_s": round(t)})
    m = {}
    g = grid_points(center, 250, 1000)
    R.measure(g)
    truth = {}
    for p in g:
        row = R.cached(p)
        if row: truth[key(p)] = row[0]
    truth = {k: v for k, v in truth.items() if v is not None}
    keys = list(truth)
    yt = [truth[k] <= TH for k in keys]
    yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
    inter = sum(1 for a, b2 in zip(yt, yp) if a and b2)
    union = sum(1 for a, b2 in zip(yt, yp) if a or b2)
    m = {"fp": sum(1 for a,b2 in zip(yt,yp) if b2 and not a),
         "fn": sum(1 for a,b2 in zip(yt,yp) if a and not b2),
         "iou": round(inter/max(1,union),3), "truth_n": len(keys), "truth_spacing": 250}
    out = {"city": label, "type": ctype, "center": list(center), "eid": eid,
           "pairs_used": R.used(), "rays": len(radii), "anisotropy": round(aniso,2),
           "radius_range": [round(min(radii.values())), round(max(radii.values()))],
           "gap_over_200m": sum(1 for g2 in gaps if g2 > 200),
           "chord_violations": chord_viol, "mid_probes": mid_probes, "mid_cleared": cleared,
           "rho": {"median": rhos[len(rhos)//2] if rhos else None, "tau_p75": tau, "hot_chords": hot},
           "islands": islands, "metrics": m,
           "radii": {f"{b:.2f}": round(v,1) for b, v in sorted(radii.items())}}
    json.dump(out, open(os.path.join(ROOT, "experiments", "results", "e10_boundary",
                                     f"e10x_{slug}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"  IoU={m['iou']} | {len(radii)}向 清零={cleared} | {R.used()}对", flush=True)
    return True

def main():
    only = set(sys.argv[1:])
    eids = [f"N6{i}" for i in range(len(CITIES))]
    for i, (slug, addr, label, ctype) in enumerate(CITIES):
        if only and slug not in only: continue
        if used(eids) >= GLOBAL_CAP:
            print(f"[{label}] 全局触顶", flush=True); break
        try:
            run_city(i, slug, addr, label, ctype)
        except Exception as e:
            print(f"[{label}] 失败:{str(e)[:150]}", flush=True)
    print(f"\nN6 总 {used(eids)} 对", flush=True)

if __name__ == "__main__":
    main()
