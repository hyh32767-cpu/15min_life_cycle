"""E4-B · 社区 B(河流/铁路切割区)采样 + 极端边界三防线 —— 在线实验

社区 B:北京·东花市大街(东侧 ~700m 为东南护城河 + 京沪铁路,典型切割地形)
流程(全部真实 API,带缓存/限流退避):
  1) 真值场:150m 网格 ±1.05km(225 对)
  2) M4:16 向同步二分(±15m),轨迹顺带做非单调检测
  3) 防线 1 弦中点验证:每条弦中点实测,违规 → 该方位加密重二分(≤3 轮)
  4) 防线 2 孤岛抽检:圈内随机 30 探针实测
  5) 留出验证 40 点(撒到 ±1150m,含河对岸)
指标:16 边形 vs 加密后多边形的 FP/FN/IoU/acc15/F1(对 150m 真值格点 + 留出点)、
     非单调点、孤岛命中 —— 与社区 A(E10)同口径对比。
预算:≤ 700 对。产出:experiments/results/e4b.json
"""
import bisect
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at
from experiments.e4_sampling.run_e4 import (Budget, cls_metrics, grid_points, idw, key)

EID = "E4B"
PAIRS_BUDGET = 700
HALF = 1050
TH = 900
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES_PATH = os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4b.json")


def pairs_used():
    db = os.path.join(_ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (EID,)).fetchone()[0]


class S:
    """社区 B 采样器:缓存 + 批量 + 限流退避(同 run_e4.Sampler,换预算表)。"""
    PACE = 1.2
    traj = []                       # (bearing, dist, T) 全轨迹

    def __init__(self, center):
        self.center = center

    def cached(self, p):
        from core import cache
        return cache.get(self.center, p)

    def measure(self, points, brg=None):
        from core import cache
        todo = [p for p in points if self.cached(p) is None]
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            if pairs_used() + len(chunk) >= PAIRS_BUDGET:
                print(f"  ⚠️ 预算触顶({pairs_used()}),截断")
                break
            for attempt in range(4):
                r = bc.routematrix("walking", [self.center], chunk, experiment_id=EID)
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
                    S.traj.append((brg, round(d, 1), it["duration_s"]))
            time.sleep(self.PACE)

    def t_of(self, p):
        row = self.cached(p)
        if row is None:
            self.measure([p])
            row = self.cached(p)
        return row[0] if row else None


def bisect_rays(S, bearings, lo=200.0, hi=1400.0, tol=15.0):
    lo_m = {b: lo for b in bearings}
    hi_m = {b: hi for b in bearings}
    S.measure([dest_at(S.center[1], S.center[0], b, 800) for b in bearings])
    active = list(bearings)
    while active:
        probs = [dest_at(S.center[1], S.center[0], b, (lo_m[b] + hi_m[b]) / 2)
                 for b in active]
        S.measure(probs)
        nxt = []
        for b, p in zip(active, probs):
            t = S.t_of(p)
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


def polar(center, p):
    d = math.hypot((p[0] - center[0]) * 111320,
                   (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
    b = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
    return d, b


def r_at(brg, radii):
    ks = sorted(radii)
    i = bisect.bisect_right(ks, brg) - 1
    b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
    db = (b1 - b0) % 360 or 360
    t = ((brg - b0) % 360) / db
    return radii[b0] * (1 - t) + radii[b1] * t


def main():
    # ---- 中心 ----
    r = bc.geocode("北京市东城区东花市大街", city="北京", experiment_id=EID)
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    print(f"社区 B 中心(bd09): {center[0]:.5f},{center[1]:.5f}")

    s = S(center)

    # ---- 真值场 150m ----
    print("== 真值场:150m 网格 ±1.05km ==")
    g150 = grid_points(center, 150, HALF)
    s.measure(g150)
    truth = {}
    for p in g150:
        row = s.cached(p)
        truth[key(p)] = row[0] if row else None
    ok_n = sum(1 for v in truth.values() if v is not None)
    print(f"  {ok_n}/{len(g150)} 对完成,累计 {pairs_used()}")

    # ---- M4 16 向二分 ----
    print("== M4:16 向同步二分 ==")
    b16 = [i * 22.5 for i in range(16)]
    radii = bisect_rays(s, b16)
    print(f"  半径: " + " ".join(f"{b:.0f}°={radii[b]:.0f}m" for b in b16[:8]) + " …")
    print(f"  累计 {pairs_used()}")

    # ---- 防线 1:弦中点验证 + 加密 ----
    print("== 防线1:弦中点验证(在线)==")
    chord_probes = chord_fixes = 0
    for round_i in range(3):
        bad = []
        ks = sorted(radii)
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            mb = ((a + b) / 2) % 360
            probe = dest_at(center[1], center[0], mb, r_at(mb, radii) * 0.97)
            s.measure([probe])
            chord_probes += 1
            t = s.t_of(probe)
            if t is not None and t > TH:
                bad.append(mb)
        if not bad:
            print(f"  第 {round_i+1} 轮:全部一致 ✓(累计探针 {chord_probes})")
            break
        print(f"  第 {round_i+1} 轮:{len(bad)} 弦违规 → 方位 {['%.1f°' % b for b in bad]}")
        radii.update(bisect_rays(s, bad))
        chord_fixes += len(bad)
        print(f"    加密重二分完成,射线 {len(radii)},累计 {pairs_used()}")

    # ---- 防线 2:孤岛抽检 ----
    print("== 防线2:内部孤岛抽检(K=30,在线)==")
    rng = random.Random(7)
    islands, probes_n = [], 0
    while probes_n < 30:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        d, b = polar(center, p)
        if d < 0.8 * r_at(b, radii):
            s.measure([p])
            probes_n += 1
            t = s.t_of(p)
            if t is not None and t > TH:
                islands.append({"bearing": round(b), "dist_m": round(d), "t_s": round(t)})
    print(f"  探针 30:孤岛命中 {len(islands)}", islands if islands else "")

    # ---- 留出验证 40 点 ----
    print("== 留出验证 40 点 ==")
    val = []
    while len(val) < 40:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 1150))
        if s.cached(p) is None:
            val.append(p)
    s.measure(val)
    val_true = [s.t_of(p) for p in val]

    # ---- 非单调检测(轨迹) ----
    per_ray = {}
    for brg, d, t in S.traj:
        per_ray.setdefault(round(brg, 1), []).append((d, t))
    nonmono = []
    for brg, seq in per_ray.items():
        seq.sort()
        for (d1, t1), (d2, t2) in zip(seq, seq[1:]):
            if t2 < t1 - 1:
                nonmono.append({"bearing": brg, "from_m": d1, "to_m": d2,
                                "t_from": round(t1), "t_to": round(t2)})

    # ---- 评估 ----
    def in_poly(p, margin=1.0):
        d, b = polar(center, p)
        return d < margin * r_at(b, radii)

    lat_keys = list(truth.keys())
    yt = [(truth[k] is not None and truth[k] <= TH) for k in lat_keys]
    yp = [in_poly((k[0], k[1])) for k in lat_keys]
    inter = sum(1 for a, b in zip(yt, yp) if a and b)
    union = sum(1 for a, b in zip(yt, yp) if a or b)
    iou = inter / max(1, union)
    fp = sum(1 for a, b in zip(yt, yp) if b and not a)
    fn = sum(1 for a, b in zip(yt, yp) if a and not b)
    pv = [in_poly(p) for p in val]
    acc, prec, rec, f1 = cls_metrics([t <= TH for t in val_true if t is not None],
                                     [p for p, t in zip(pv, val_true) if t is not None])

    print("\n===== 社区 B 结果 =====")
    print(f"最终射线数 {len(radii)} | 弦探针 {chord_probes} | 加密 {chord_fixes} 向 | "
          f"孤岛 {len(islands)} | 非单调段 {len(nonmono)}")
    print(f"对 150m 真值格点(n={len(lat_keys)}):FP={fp} FN={fn} IoU={iou:.3f}")
    print(f"对留出 40 点:acc15={acc:.3f} F1={f1:.3f}")
    print(f"总消耗 {pairs_used()} 对")

    json.dump({"experiment": EID, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "center": list(center), "pairs_used": pairs_used(),
               "radii_final": {f"{b:.1f}": round(v, 1) for b, v in sorted(radii.items())},
               "chord_probes": chord_probes, "chord_fixes": chord_fixes,
               "islands": islands, "non_monotonic": nonmono,
               "metrics": {"fp": fp, "fn": fn, "iou150": round(iou, 3),
                           "acc15": round(acc, 3), "f1": round(f1, 3)},
               "truth_field": {f"{k[0]:.6f},{k[1]:.6f}": v for k, v in truth.items()}},
              open(RES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已写入 {RES_PATH}")


if __name__ == "__main__":
    main()
