"""E4 离线复核分析(零 API 调用,数据来自 cache.db 重放)。

修正两个评估偏差:
  1. IoU 改在 50m 格点(761 点)上评估,并标注 M2/M8 的样本内偏差;
  2. 边界参考场改用全量缓存场(2331 点,当前最优真值近似);
  3. 二分轨迹确定性重放,重建 M4/M7 样本集。
产出:experiments/results/e4_analysis.json
"""
import json
import math
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from experiments.e4_sampling.run_e4 import (flat_m, grid_points, idw, boundary_radius,
                                cls_metrics, key, TH)
from core.coord import dest_at

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_cache_field(center):
    """读 cache.db,取该中心的所有 (dest -> duration)。"""
    db = os.path.join(_ROOT, "experiments", "logs", "cache.db")
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT d_lat, d_lng, duration_s FROM walk_times"
                         " WHERE mode='walking' AND o_lat=? AND o_lng=?",
                         (round(center[0], 6), round(center[1], 6))).fetchall()
    return {(lat, lng): t for lat, lng, t in rows}


def replay_bisect(field, center, bearings, lo=200.0, hi=1400.0, tol=15.0):
    """用缓存场确定性重放二分轨迹,返回 (每向半径, 轨迹样本点集)。"""
    def t_at(d, b):
        k = key(dest_at(center[1], center[0], b, d))
        return field.get(k)
    samples = {}
    lo_m, hi_m = {}, {}
    for b in bearings:
        k = key(dest_at(center[1], center[0], b, 800))
        samples[k] = field.get(k)
    lo_m = {b: lo for b in bearings}
    hi_m = {b: hi for b in bearings}
    active = list(bearings)
    while active:
        nxt = []
        for b in active:
            m = (lo_m[b] + hi_m[b]) / 2
            k = key(dest_at(center[1], center[0], b, m))
            samples[k] = field.get(k)
            t = field.get(k)
            if t is None:
                continue
            if t <= TH:
                lo_m[b] = m
            else:
                hi_m[b] = m
            if hi_m[b] - lo_m[b] > tol:
                nxt.append(b)
        active = nxt
    return {b: (lo_m[b] + hi_m[b]) / 2 for b in bearings}, samples


def main():
    e0 = json.load(open(os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e0.json"),
                        encoding="utf-8"))
    center = tuple(e0["center"])
    field = load_cache_field(center)
    print(f"缓存场:{len(field)} 点")

    # 重建各方法样本集(确定性)
    m2_keys = {key(p) for p in grid_points(center, 100, 1000)}
    m1_keys = {key(p) for p in grid_points(center, 200, 1000)}
    m3_keys = {key(p) for p in grid_points(center, 50, 500)}
    M1 = {k: field[k] for k in m1_keys if k in field}
    M2 = {k: field[k] for k in m2_keys if k in field}
    M3 = {k: field[k] for k in (m2_keys | m3_keys) if k in field}   # 100m 全域 + 50m 中心加密
    b16 = [i * 22.5 for i in range(16)]
    r16, M4 = replay_bisect(field, center, b16)
    r_ad = dict(replay_bisect(field, center, list(range(0, 360, 45)))[0])
    # 自适应插入向(重放)
    _, s8 = replay_bisect(field, center, list(range(0, 360, 45)))
    M7 = dict(s8)
    for _ in range(3):
        brgs = sorted(r_ad)
        gaps = [((a + b) / 2) % 360 for a, b in zip(brgs, brgs[1:] + [brgs[0] + 360])
                if b - a > 22.5 and abs(r_ad[a % 360] - r_ad[b % 360]) > 150]
        if not gaps:
            break
        radii, smp = replay_bisect(field, center, gaps)
        r_ad.update(radii)
        M7.update(smp)
    # M8 = M2 + 边界带加密(重放:band 单元的对角半步点)
    band = [k for k, t in M2.items() if t is not None and 720 <= t <= 1080]
    M8 = dict(M2)
    refine_keys = set()
    for (lat, lng) in band:
        for brg in (45, 135, 225, 315):
            k = key(dest_at(lng, lat, brg, 35))
            if k in field:
                M8[k] = field[k]
                refine_keys.add(k)

    # 验证点识别:缓存全集 − 各方法已知样本 = 恰好 80 个 held-out 点
    known = (set(M2) | set(M3) | set(M4) | set(M7) | refine_keys)
    val_keys = sorted(set(field) - known)
    assert len(val_keys) == 80, f"验证点识别异常:{len(val_keys)} 个"
    val = val_keys
    val_true = [field[k] for k in val]

    methods = {
        "M1 网格200m":   (M1, 121),
        "M2 网格100m":   (M2, 441),
        "M3 100m+50m加密": (M3, len(m2_keys | m3_keys)),
        "M4 扇形16+二分": (M4, len(M4)),
        "M7 自适应扇形":  (M7, len(M7)),
        "M8 边界带AMR":  (M8, 441 + (len(M8) - len(M2))),
    }
    # 参考场 = 全量缓存场
    ref_bnd = {b: boundary_radius(center, field, b) for b in range(0, 360, 45)}
    lat50 = list(M3.keys())
    truth50 = [(field[k] is not None and field[k] <= TH) for k in lat50]

    print(f"\n===== 修订杀手表(社区A·王府井;验证 80 点为留出集)=====")
    print(f"{'方法':<14}{'独立对数':>7}{'请求':>4}{'MAE_s':>7}{'RMSE':>7}"
          f"{'acc15':>7}{'F1':>6}{'IoU@50m':>8}{'边界Δm':>7}")
    rows = []
    for name, (smp, standalone) in methods.items():
        pv = idw(smp, val)
        pairs = [(a, b) for a, b in zip(val_true, pv) if a is not None and b is not None]
        err = [b - a for a, b in pairs]
        mae = statistics.mean(abs(e) for e in err)
        rmse = math.sqrt(statistics.mean(e * e for e in err))
        acc, prec, rec, f1 = cls_metrics([a <= TH for a, _ in pairs],
                                         [b <= TH for _, b in pairs])
        pg = idw(smp, lat50)
        yg = [p is not None and p <= TH for p in pg]
        inter = sum(1 for a, b in zip(truth50, yg) if a and b)
        union = sum(1 for a, b in zip(truth50, yg) if a or b)
        iou = inter / max(1, union)
        berrs = [abs(boundary_radius(center, smp, b) - ref_bnd[b])
                 for b in range(0, 360, 45)
                 if ref_bnd[b] and boundary_radius(center, smp, b)]
        rows.append({"method": name, "pairs": standalone,
                     "requests": math.ceil(standalone / 50),
                     "mae_s": round(mae, 1), "rmse_s": round(rmse, 1),
                     "acc15": round(acc, 3), "f1": round(f1, 3),
                     "iou50": round(iou, 3),
                     "bnd_err_m": round(statistics.mean(berrs), 1) if berrs else None})
        r = rows[-1]
        print(f"{name:<14}{r['pairs']:>7}{r['requests']:>4}{r['mae_s']:>7}{r['rmse_s']:>7}"
              f"{r['acc15']:>7}{r['f1']:>6}{r['iou50']:>8}{r['bnd_err_m'] or '-':>7}")

    json.dump({"experiment": "E4-analysis", "center": list(center),
               "ref_boundaries_m": {str(b): round(v, 1) for b, v in ref_bnd.items()},
               "methods": rows},
              open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4_analysis.json"),
                   "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # 评估基准固化:供后续方法(H3 AMR 等)以完全同一口径离线复用
    json.dump({"center": list(center),
               "val": [[k[0], k[1]] for k in val],
               "val_true": val_true,
               "lat50": [[k[0], k[1]] for k in lat50],
               "truth50": truth50,
               "ref_boundaries_m": {str(b): round(v, 1) for b, v in ref_bnd.items()}},
              open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"),
                   "w", encoding="utf-8"), ensure_ascii=False)
    print("\n已写入 e4_analysis.json + eval_setup.json(评估基准)")


if __name__ == "__main__":
    main()
