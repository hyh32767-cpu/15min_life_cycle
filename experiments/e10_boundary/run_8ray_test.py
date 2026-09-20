"""E10-8R · 初始 8 向可行性实验(射线上限锁死 8,加向禁用)

对象:成都·九眼桥(预期简单,anisotropy 1.27)/ 哈尔滨·道外(已知最难,2.25)
问题:8 向起步 + 防线(mid 探针,但**不插新射线**)能撑住吗?
判读:
  - mid 探针全部一致 → 8 向足够,生产线可再省一半
  - 出现无法修复的违规弦 → 8 向不够,验证地形感知升级规则的必要性
协议:8 向二分(容差 50m,OSMnx 结论)+ mid 探针 2 轮(只探不加向)+ 孤岛 K=10
评估:vs 该城既有真值格点(150-250m)+ 参考多边形(16/32 向成品)。
产出:experiments/results/e10_8ray.json
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
from experiments.e4_sampling.run_e4 import cls_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
PAIRS_CAP = 400
TARGETS = [
    ("chengdu", "e10_boundary/e10x_chengdu.json", "成都·九眼桥"),
    ("harbin", "e10_boundary/e10x_harbin.json", "哈尔滨·道外"),
]


def used(eid):
    db = os.path.join(ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (eid,)).fetchone()[0]


class Runner:
    PACE = 1.2

    def __init__(self, eid, center):
        self.eid, self.center = eid, center

    def left(self):
        return PAIRS_CAP - used(self.eid)

    def cached(self, p):
        return cache.get(self.center, p)

    def measure(self, points):
        todo = [p for p in points if self.cached(p) is None]
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            if self.left() < len(chunk):
                print(f"  ⚠️ 预算触顶,截断")
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
            time.sleep(self.PACE)

    def t_of(self, p):
        row = self.cached(p)
        if row is None:
            self.measure([p])
            row = self.cached(p)
        return row[0] if row else None

    def bisect(self, bearings, tol=50.0, lo=200.0, hi=1400.0):
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


def r_at(brg, radii):
    ks = sorted(radii)
    i = bisect.bisect_right(ks, brg) - 1
    b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
    db = (b1 - b0) % 360 or 360
    t = ((brg - b0) % 360) / db
    return radii[b0] * (1 - t) + radii[b1] * t


def run(slug, fname, label):
    d = json.load(open(os.path.join(ROOT, "experiments", "results", fname), encoding="utf-8"))
    center = tuple(d["center"])
    ref_radii = {float(k): v for k, v in d["radii"].items()}
    spacing = d.get("metrics", {}).get("truth_spacing")
    print(f"\n===== {label} | 8 向锁定实验 =====")
    R = Runner(f"E10R8-{slug}", center)
    b8 = [i * 45.0 for i in range(8)]
    radii8 = R.bisect(b8, tol=50.0)
    print(f"8 向二分完成(tol50),累计 {used(R.eid)} 对;"
          f"半径 {min(radii8.values()):.0f}-{max(radii8.values()):.0f}m")

    # mid 探针 2 轮(不插射线,只记录)
    unresolved = []
    for rd in range(2):
        bad = []
        ks = sorted(radii8)
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            mb = ((a + b) / 2) % 360
            probe = dest_at(center[1], center[0], mb, r_at(mb, radii8) * 0.97)
            R.measure([probe])
            t = R.t_of(probe)
            if t is not None and t > TH:
                bad.append((round(mb, 1), round(t)))
        if not bad:
            print(f"  mid 第{rd+1}轮:全部一致 ✓(8 向足够)")
            break
        print(f"  mid 第{rd+1}轮:{len(bad)} 弦违规 {bad}(8 向下无法修复→记录)")
        unresolved = bad

    # 弦差(免费复杂度信号在 8 向下读数)
    gaps = []
    ks = sorted(radii8)
    for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
        gaps.append(round(abs(radii8[a % 360] - radii8[b % 360])))

    # 孤岛 K=10
    rng = random.Random(5)
    islands, n = [], 0
    while n < 10 and R.left() > 30:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 900))
        dd, b = R.polar(p)
        if dd < 0.8 * r_at(b, radii8):
            R.measure([p])
            n += 1
            t = R.t_of(p)
            if t is not None and t > TH:
                islands.append({"b": round(b), "d": round(dd), "t": round(t)})

    # 评估:对参考多边形(真值格点标签 = 参考场实测,载入缓存)
    db = os.path.join(ROOT, "experiments", "logs", "cache.db")
    field = {}
    with sqlite3.connect(db) as c:
        for d_lat, d_lng, dur in c.execute(
                "SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=?",
                (round(center[0], 6), round(center[1], 6))):
            if dur is not None:
                field[(d_lat, d_lng)] = dur

    def in_poly(p, radii):
        dd, b = R.polar(p)
        return dd < r_at(b, radii)

    res = {}
    if spacing:
        from experiments.e4_sampling.run_e4 import grid_points, key
        g = grid_points(center, spacing, 1000 if spacing != 150 else 1050)
        keys = [p for p in g if key(p) in field]
        yt = [field[key(p)] <= TH for p in keys]
        for name, rr in (("8向", radii8), ("参考(成品)", ref_radii)):
            yp = [in_poly(p, rr) for p in keys]
            acc, prec, rec, f1 = cls_metrics(yt, yp)
            inter = sum(1 for a, b2 in zip(yt, yp) if a and b2)
            union = sum(1 for a, b2 in zip(yt, yp) if a or b2)
            res[name] = {"f1": round(f1, 3), "iou": round(inter / max(1, union), 3),
                         "n": len(keys)}
            print(f"  {name}:F1={f1:.3f} IoU={inter/max(1,union):.3f}(n={len(keys)})")
        # 边界一致性:8向 vs 参考,8 主方向
        bd = [abs(r_at(b, radii8) - r_at(b, ref_radii)) for b in range(0, 360, 45)]
        res["bnd_vs_ref_m"] = round(float(sum(bd) / len(bd)), 1)
        print(f"  边界 8向 vs 成品:平均Δ{res['bnd_vs_ref_m']}m")

    out = {"label": label, "pairs": used(R.eid), "radii8": {f"{b:.1f}": round(v, 1)
                                                            for b, v in radii8.items()},
           "gaps_45deg": gaps, "unresolved_chords": unresolved, "islands": islands,
           "metrics": res}
    return out


def main():
    results = {}
    for slug, fname, label in TARGETS:
        results[slug] = run(slug, fname, label)
    json.dump(results, open(os.path.join(ROOT, "experiments", "results", "e10_boundary", "e10_8ray.json"),
                            "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/e10_8ray.json")


if __name__ == "__main__":
    main()
