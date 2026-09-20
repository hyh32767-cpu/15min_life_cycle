"""E10-X · 四城四类社区 E10 三探针管线迁移验证(在线)

城市与类型:
  0 上海·陆家嘴    CBD 超级街区 + 黄浦江(宽江少桥)
  1 广州·上下九    老城窄巷 + 河涌
  2 成都·九眼桥    规则路网 + 府河
  3 哈尔滨·道外    北方老城 + 松花江支流/铁路

每城流程(预算 ≤460 对,方法优先、真值用剩余预算):
  1) geocode 定中心
  2) 16 向同步二分(轨迹记录)
  3) 免费复杂度信号:相邻半径差;≥2 条 >200m → 补满 32 向(地形感知起步)
  4) 防线1 mid 探针(首轮全弦,后续仅新弦)→ 违规方位重二分,≤3 轮
  5) ρ 探针:最终多边形 ≤24 条弦的端点间步行时间(单发)
  6) 防线2 孤岛抽检 K=15
  7) 真值网格:剩余预算 ≥121 对 → 200m;≥81 → 250m;否则跳过
指标:FP/FN/IoU(vs 真值格点)、弦违规数、孤岛、ρ 统计、各向异性、非单调段。

用法:python run_e10_cities.py <0|1|2|3|all>
产出:experiments/results/e10x_{城市}.json
"""
import bisect
import json
import math
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache
from core.coord import dest_at
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, key

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
WALK_MS = 1.083
CITIES = [
    ("shanghai", "上海市浦东新区陆家嘴环路", "上海·陆家嘴", "CBD超级街区+黄浦江"),
    ("guangzhou", "广州市荔湾区上下九步行街", "广州·上下九", "老城窄巷+河涌"),
    ("chengdu", "成都市锦江区九眼桥", "成都·九眼桥", "规则路网+府河"),
    ("harbin", "哈尔滨市道外区中华巴洛克历史文化街区", "哈尔滨·道外", "北方老城+江/铁路"),
]


class CityRunner:
    PACE = 1.2

    def __init__(self, eid, center, cap=460):
        self.eid, self.center, self.cap = eid, center, cap
        self.traj = []

    def used(self):
        db = os.path.join(_ROOT, "experiments", "logs", "calls.db")
        with sqlite3.connect(db) as c:
            return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                             (self.eid,)).fetchone()[0]

    def left(self):
        return self.cap - self.used()

    def cached(self, p):
        return cache.get(self.center, p)

    def measure(self, points, brg=None):
        todo = [p for p in points if self.cached(p) is None]
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            if self.left() < len(chunk):
                print(f"  ⚠️ 预算触顶({self.used()}/{self.cap}),截断")
                return
            for attempt in range(4):
                r = bc.routematrix("walking", [self.center], chunk, experiment_id=self.eid)
                if r.ok:
                    break
                if r.status == 401 and attempt < 3:
                    w = [15, 30, 60][attempt]
                    print(f"  ⚠️ 401 退避 {w}s")
                    time.sleep(w)
                    continue
                raise RuntimeError(f"matrix {r.status} {r.message}")
            for p, it in zip(chunk, bc.matrix_items(r)):
                cache.put(self.center, p, it["duration_s"], it["distance_m"])
                if brg is not None:
                    d = math.hypot((p[0] - self.center[0]) * 111320,
                                   (p[1] - self.center[1]) * 111320
                                   * math.cos(math.radians(self.center[0])))
                    self.traj.append((brg, round(d, 1), it["duration_s"]))
            time.sleep(self.PACE)

    def t_of(self, p):
        row = self.cached(p)
        if row is None:
            self.measure([p])
            row = self.cached(p)
        return row[0] if row else None

    # ---- 二分(跨射线同步批量)----
    def bisect(self, bearings, lo=200.0, hi=1400.0, tol=15.0):
        lo_m = {b: lo for b in bearings}
        hi_m = {b: hi for b in bearings}
        self.measure([dest_at(self.center[1], self.center[0], b, 800) for b in bearings])
        active = list(bearings)
        while active:
            probs = [dest_at(self.center[1], self.center[0], b, (lo_m[b] + hi_m[b]) / 2)
                     for b in active]
            self.measure(probs)
            nxt = []
            for b, p in zip(active, probs):
                t = self.t_of(p)
                if t is None:
                    continue
                if t <= TH:
                    lo_m[b] = (lo_m[b] + hi_m[b]) / 2
                else:
                    hi_m[b] = (lo_m[b] + hi_m[b]) / 2
                if hi_m[b] - lo_m[b] > tol:
                    nxt.append(b)
            active = nxt
        return {b: (lo_m[b] + hi_m[b]) / 2 for b in bearings}

    def polar(self, p):
        d = math.hypot((p[0] - self.center[0]) * 111320,
                       (p[1] - self.center[1]) * 111320
                       * math.cos(math.radians(self.center[0])))
        b = math.degrees(math.atan2(p[1] - self.center[1], p[0] - self.center[0])) % 360
        return d, b

    def r_at(self, brg, radii):
        ks = sorted(radii)
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    def endpoint(self, b, r):
        return dest_at(self.center[1], self.center[0], b, r)


def run_city(idx):
    slug, addr, label, ctype = CITIES[idx]
    eid = f"E10X{idx}"
    r = bc.geocode(addr, experiment_id=eid)
    if not r.ok:
        print(f"[{label}] geocode 失败:{r.message}")
        return
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    print(f"\n===== [{idx}] {label}({ctype})===== 中心 {center[0]:.5f},{center[1]:.5f}")

    R = CityRunner(eid, center)
    b16 = [i * 22.5 for i in range(16)]
    radii = R.bisect(b16)
    print(f"16 向二分完成({R.used()} 对);半径 {min(radii.values()):.0f}–{max(radii.values()):.0f}m")

    # 地形感知:≥2 条弦差 >200m → 补 32 向
    gaps = []
    for a, b in zip(b16, b16[1:] + [b16[0] + 360]):
        gaps.append(abs(radii[a % 360] - radii[b % 360]))
    if sum(1 for g in gaps if g > 200) >= 2 and R.left() > 180:
        print("  复杂信号(≥2 弦差>200m)→ 补满 32 向")
        radii.update(R.bisect([b + 11.25 for b in b16]))
    aniso = max(radii.values()) / max(1e-9, min(radii.values()))

    # 防线1:mid 探针(首轮全弦;后续仅新弦)
    chord_viol, mid_probes = [], 0
    new_bearings = None
    for rd in range(3):
        ks = sorted(radii)
        pairs_list = list(zip(ks, ks[1:] + [ks[0] + 360]))
        if new_bearings is not None:                     # 只测与新插入射线相邻的弦
            pairs_list = [(a, b) for a, b in pairs_list
                          if any(abs(((a + b) / 2) % 360 - nb) < 1e-6 for nb in new_bearings)]
        bad = []
        for a, b in pairs_list:
            mb = ((a + b) / 2) % 360
            probe = R.endpoint(mb, R.r_at(mb, radii) * 0.97)
            R.measure([probe])
            mid_probes += 1
            t = R.t_of(probe)
            if t is not None and t > TH:
                bad.append(mb)
                chord_viol.append(round(mb, 1))
        if not bad:
            print(f"  mid 第{rd+1}轮一致 ✓(累计探针 {mid_probes})")
            break
        print(f"  mid 第{rd+1}轮:{len(bad)} 弦违规 {['%.1f°' % x for x in bad]}")
        radii.update(R.bisect(bad))
        new_bearings = bad

    # ρ 探针(最终多边形前 24 条弦,单发)
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
    rho_hot = [x["chord"] for x in rho_rows if x["rho"] and tau and x["rho"] > max(tau, 1.8)]

    # 防线2:孤岛抽检 K=15
    rng = random.Random(11)
    islands, probes_n = [], 0
    while probes_n < 15 and R.left() > 60:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        d, b = R.polar(p)
        if d < 0.8 * R.r_at(b, radii):
            R.measure([p])
            probes_n += 1
            t = R.t_of(p)
            if t is not None and t > TH:
                islands.append({"bearing": round(b), "dist_m": round(d), "t_s": round(t)})

    # 真值网格(剩余预算决定分辨率)
    spacing = None
    if R.left() >= 121:
        spacing = 200
    elif R.left() >= 81:
        spacing = 250
    truth = {}
    if spacing:
        g = grid_points(center, spacing, 1000)
        R.measure(g)
        for p in g:
            row = R.cached(p)
            truth[key(p)] = row[0] if row else None
        truth = {k: v for k, v in truth.items() if v is not None}

    # 评估
    m = {}
    if truth:
        keys = list(truth.keys())
        yt = [truth[k] <= TH for k in keys]
        yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
        inter = sum(1 for a, b in zip(yt, yp) if a and b)
        union = sum(1 for a, b in zip(yt, yp) if a or b)
        m = {"fp": sum(1 for a, b in zip(yt, yp) if b and not a),
             "fn": sum(1 for a, b in zip(yt, yp) if a and not b),
             "iou": round(inter / max(1, union), 3), "truth_n": len(keys),
             "truth_spacing": spacing}

    # 非单调段
    per_ray = {}
    for brg, d, t in R.traj:
        per_ray.setdefault(round(brg, 1), []).append((d, t))
    nonmono = 0
    for seq in per_ray.values():
        seq.sort()
        nonmono += sum(1 for (d1, t1), (d2, t2) in zip(seq, seq[1:]) if t2 < t1 - 1)

    out = {"city": label, "type": ctype, "center": list(center), "eid": eid,
           "pairs_used": R.used(), "rays": len(radii), "anisotropy": round(aniso, 2),
           "radius_range": [round(min(radii.values())), round(max(radii.values()))],
           "gap_over_200m": sum(1 for g in gaps if g > 200),
           "chord_violations": chord_viol, "mid_probes": mid_probes,
           "rho": {"median": rhos[len(rhos) // 2] if rhos else None,
                   "tau_p75": tau, "hot_chords": rho_hot},
           "islands": islands, "non_monotonic": nonmono,
           "metrics": m,
           "radii": {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}}
    json.dump(out, open(os.path.join(_ROOT, "experiments", "results", "e10_boundary", f"e10x_{slug}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"结果:射线{len(radii)} 各向异性{aniso:.2f} 弦违规{len(chord_viol)} "
          f"孤岛{len(islands)} 非单调{nonmono} ρ中位{out['rho']['median']} "
          f"FP={m.get('fp')} FN={m.get('fn')} IoU={m.get('iou')} | 共 {R.used()} 对")


if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    if args == ["all"] or args[0] == "all":
        for i in range(4):
            run_city(i)
    else:
        run_city(int(args[0]))
