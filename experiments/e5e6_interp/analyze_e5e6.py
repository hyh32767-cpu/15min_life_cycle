"""E5+E6 · 插值方法对比 + 绕行系数跨城标定(零 API,全部来自缓存场)

E6:社区 A(有 80 留出点)上,三套样本 × 六种插值:
    样本:M2 100m 网格 / M4 射线轨迹 / M8 边界带 AMR
    方法:IDW p=1/2/3、Delaunay 线性(griddata)、最近邻(下界参照)
    指标:留出点 MAE / RMSE / acc15 / F1
E5:六社区全部缓存对 → 绕行系数(route_dist / 直线)分布 + 分区标定 + 兜底精度:
    固定系数 1.2/1.3/1.4 vs 城市中位 vs 城市内分区(方位×距离带)
    兜底预测 T = 直线 × k / v(v 用城市实测中位步速)
产出:experiments/results/e5e6.json + 控制台报告
"""
import json
import math
import os
import statistics
import sys

import numpy as np
from scipy.interpolate import griddata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e4_sampling.analyze_e4 import load_cache_field, replay_bisect
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, key

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
WALK_MS = 1.083


def e6(setup, field):
    center = tuple(setup["center"])
    val = [tuple(v) for v in setup["val"]]
    val_true = setup["val_true"]

    m2_keys = {key(p) for p in grid_points(center, 100, 1000)}
    m2 = {k: field[k] for k in m2_keys if k in field and field[k] is not None}
    _, rays = replay_bisect(field, center, [i * 22.5 for i in range(16)])
    rays = {k: t for k, t in rays.items() if t is not None}
    band = [k for k, t in m2.items() if 720 <= t <= 1080]
    m8 = dict(m2)
    from core.coord import dest_at
    for (lat, lng) in band:
        for brg in (45, 135, 225, 315):
            k = key(dest_at(lng, lat, brg, 35))
            if k in field and field[k] is not None:
                m8[k] = field[k]

    samplers = {"M2 网格100m": m2, "M4 射线轨迹": rays, "M8 AMR": m8}

    def idw_p(samples, points, p):
        out = []
        for pt in points:
            num = den = 0.0
            for (lat, lng), t in samples.items():
                d = math.hypot((lat - pt[0]) * 111320,
                               (lng - pt[1]) * 111320 * math.cos(math.radians(pt[0])))
                if d < 1e-6:
                    num, den = t, 1.0
                    break
                w = 1.0 / (d ** p)
                num += w * t
                den += w
            out.append(num / den if den else None)
        return out

    def grid_interp(samples, points, method):
        pts = np.array([(k[0], k[1]) for k in samples])
        vals = np.array([samples[k] for k in samples])
        tgt = np.array(points)
        out = griddata(pts, vals, tgt, method=method)
        return [None if (x is None or np.isnan(x)) else float(x) for x in out]

    methods = {
        "IDW p=1": lambda s, p: idw_p(s, p, 1),
        "IDW p=2": lambda s, p: idw_p(s, p, 2),
        "IDW p=3": lambda s, p: idw_p(s, p, 3),
        "线性Delaunay": lambda s, p: grid_interp(s, p, "linear"),
        "最近邻(下界)": lambda s, p: grid_interp(s, p, "nearest"),
    }
    rows = []
    print("== E6 插值对比(社区 A,80 留出点)==")
    print(f"{'样本':<10}{'方法':<12}{'MAE_s':>7}{'RMSE':>7}{'acc15':>7}{'F1':>6}")
    for sname, smp in samplers.items():
        for mname, fn in methods.items():
            try:
                pv = fn(smp, val)
            except Exception as e:
                print(f"{sname:<10}{mname:<12} 失败:{str(e)[:40]}")
                continue
            prs = [(a, b) for a, b in zip(val_true, pv) if a is not None and b is not None]
            err = [b - a for a, b in prs]
            mae = statistics.mean(abs(e) for e in err)
            rmse = math.sqrt(statistics.mean(e * e for e in err))
            acc, prec, rec, f1 = cls_metrics([a <= TH for a, _ in prs],
                                             [b <= TH for _, b in prs])
            rows.append({"sampler": sname, "method": mname,
                         "mae_s": round(mae, 1), "rmse_s": round(rmse, 1),
                         "acc15": round(acc, 3), "f1": round(f1, 3)})
            print(f"{sname:<10}{mname:<12}{mae:>7.1f}{rmse:>7.1f}{acc:>7.3f}{f1:>6.3f}")
    return rows


def load_all_fields():
    """cache.db 里全部 origin → {dest: (duration, distance)}。"""
    import sqlite3
    db = os.path.join(_ROOT, "experiments", "logs", "cache.db")
    fields = {}
    with sqlite3.connect(db) as c:
        for o_lat, o_lng, d_lat, d_lng, dur, dist in c.execute(
                "SELECT o_lat,o_lng,d_lat,d_lng,duration_s,distance_m FROM walk_times"):
            fields.setdefault((o_lat, o_lng), {})[(d_lat, d_lng)] = (dur, dist)
    return fields


def flat(o, p):
    return math.hypot((p[0] - o[0]) * 111320,
                      (p[1] - o[1]) * 111320 * math.cos(math.radians(o[0])))


def e5(fields, names):
    print("\n== E5 绕行系数跨城标定(全部缓存对)==")
    out = {}
    print(f"{'社区':<12}{'n':>6}{'P25':>6}{'中位':>6}{'P75':>6}{'P95':>6}{'max':>6}"
          f"{'中位步速':>8}{'兜底MAE(最优k)':>14}{'acc15':>7}")
    for origin, pts in sorted(fields.items()):
        name = names.get(origin, f"{origin[0]:.4f},{origin[1]:.4f}")
        if len(pts) < 80:
            continue
        det, spd, pairs = [], [], []
        for d_, (dur, dist) in pts.items():
            if not dur or not dist:
                continue
            s = flat(origin, d_)
            if s < 100:
                continue
            det.append(dist / s)
            spd.append(dist / dur * 3.6)
            pairs.append((s, dist, dur))
        if len(det) < 60:
            continue
        det_s = sorted(det)
        q = lambda p: det_s[int(p * (len(det_s) - 1))]
        v_city = statistics.median(spd) / 3.6          # m/s

        # 分区系数:方位 8 扇区 × 距离带 {100-600, 600-1000, 1000+}
        def sector_of(p):
            b = math.degrees(math.atan2(p[1] - origin[1], p[0] - origin[0])) % 360
            return int(b // 45)

        cells = {}
        for d_, (dur, dist) in pts.items():
            if not dist:
                continue
            s = flat(origin, d_)
            if s < 100:
                continue
            band = 0 if s < 600 else (1 if s < 1000 else 2)
            cells.setdefault((sector_of(d_), band), []).append(dist / s)
        cell_k = {kc: statistics.median(vs) for kc, vs in cells.items() if len(vs) >= 3}

        def fallback(s, dist, k):
            return s * k / v_city

        best = None
        for kname, kfn in [
            ("k=1.2", lambda s, dist, sec: 1.2), ("k=1.3", lambda s, dist, sec: 1.3),
            ("k=1.4", lambda s, dist, sec: 1.4),
            ("城市中位", lambda s, dist, sec: statistics.median(det)),
            ("分区中位", lambda s, dist, sec: cell_k.get((sec, 0 if s < 600 else (1 if s < 1000 else 2)),
                                                          statistics.median(det))),
        ]:
            errs, cls = [], []
            for d_, (dur, dist) in pts.items():
                if not dur or not dist:
                    continue
                s = flat(origin, d_)
                if s < 100:
                    continue
                pred = s * kfn(s, dist, sector_of(d_)) / v_city
                errs.append(abs(pred - dur))
                cls.append((pred <= TH) == (dur <= TH))
            mae = statistics.mean(errs)
            acc = statistics.mean(cls)
            if best is None or mae < best[1]:
                best = (kname, mae, acc)
        out[name] = {"n": len(det), "p25": round(q(.25), 2), "median": round(q(.5), 2),
                     "p75": round(q(.75), 2), "p95": round(q(.95), 2),
                     "max": round(max(det), 2), "speed_kmh": round(v_city * 3.6, 1),
                     "best_fallback": {"k": best[0], "mae_s": round(best[1]),
                                       "acc15": round(best[2], 3)},
                     "cell_k": {f"{a}-{b}": round(v, 2) for (a, b), v in sorted(cell_k.items())}}
        o = out[name]
        print(f"{name:<12}{o['n']:>6}{o['p25']:>6}{o['median']:>6}{o['p75']:>6}"
              f"{o['p95']:>6}{o['max']:>6}{o['speed_kmh']:>8}"
              f"{o['best_fallback']['k'] + ' ' + str(o['best_fallback']['mae_s']) + 's':>14}"
              f"{o['best_fallback']['acc15']:>7}")
    return out


def main():
    setup = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"), encoding="utf-8"))
    fieldA = load_cache_field(tuple(setup["center"]))
    e6rows = e6(setup, fieldA)

    names = {}
    for tag, f in [("北京A·王府井", "e4_sampling/e4.json"),
                   ("北京B·东花市", "e4_sampling/e4b.json"),
                   ("上海·陆家嘴", "e10_boundary/e10x_shanghai.json"),
                   ("广州·上下九", "e10_boundary/e10x_guangzhou.json"),
                   ("成都·九眼桥", "e10_boundary/e10x_chengdu.json"),
                   ("哈尔滨·道外", "e10_boundary/e10x_harbin.json")]:
        fp = os.path.join(_ROOT, "experiments", "results", f)
        if os.path.exists(fp):
            c = json.load(open(fp, encoding="utf-8"))["center"]
            names[(round(c[0], 6), round(c[1], 6))] = tag
    e5rows = e5(load_all_fields(), names)

    json.dump({"e6": e6rows, "e5": e5rows},
              open(os.path.join(_ROOT, "experiments", "results", "e5e6_interp", "e5e6.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/e5e6.json")


if __name__ == "__main__":
    main()
