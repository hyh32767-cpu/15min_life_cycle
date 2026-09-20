"""M9 · 组合采样(射线二分 + 稀疏内部填充)—— 离线模拟,零 API。

设计要点(与"拼接两方法"的区别):
  1. 16 向二分(~112 对)负责边界:轨迹天然包含界内外成对探针(±15m)
  2. 内部只铺 200m 稀疏网格,且只测"射线场判定的深内部(T≤12min)"点
  3. 圈外不测任何点 —— 分类由边界探针外推承担
对照变体:
  M9a 内部 200m 填充
  M9b 内部 400m 填充(极预算)
评估与 M1–M8/MH 完全同口径(eval_setup.json)。
"""
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e4_sampling.analyze_e4 import load_cache_field, replay_bisect
from experiments.e4_sampling.run_e4 import boundary_radius, cls_metrics, grid_points, idw, key

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900


def main():
    setup = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"), encoding="utf-8"))
    center = tuple(setup["center"])
    field = load_cache_field(center)

    b16 = [i * 22.5 for i in range(16)]
    r16, rays = replay_bisect(field, center, b16)
    n_ray = len(rays)

    def r_at(bearing):
        """相邻两向半径线性插值。"""
        ks = sorted(r16)
        import bisect
        i = bisect.bisect_right(ks, bearing) - 1
        b0, b1 = ks[i % 16], ks[(i + 1) % 16]
        db = (b1 - b0) % 360 or 360
        t = ((bearing - b0) % 360) / db
        return r16[b0] * (1 - t) + r16[b1] * t

    val = [tuple(v) for v in setup["val"]]
    val_true = setup["val_true"]
    lat50 = [tuple(v) for v in setup["lat50"]]
    truth50 = setup["truth50"]
    ref_bnd = {int(b): v for b, v in setup["ref_boundaries_m"].items()}

    def evaluate(name, samples, pairs):
        pv = idw(samples, val)
        prs = [(a, b) for a, b in zip(val_true, pv) if a is not None and b is not None]
        err = [b - a for a, b in prs]
        mae = statistics.mean(abs(e) for e in err)
        rmse = math.sqrt(statistics.mean(e * e for e in err))
        acc, prec, rec, f1 = cls_metrics([a <= TH for a, _ in prs],
                                         [b <= TH for _, b in prs])
        pg = idw(samples, lat50)
        yg = [p is not None and p <= TH for p in pg]
        inter = sum(1 for a, b in zip(truth50, yg) if a and b)
        union = sum(1 for a, b in zip(truth50, yg) if a or b)
        iou = inter / max(1, union)
        berrs = [abs(boundary_radius(center, samples, b) - ref_bnd[b]) for b in range(0, 360, 45)
                 if ref_bnd[b] and boundary_radius(center, samples, b)]
        row = {"method": name, "pairs": pairs, "requests": math.ceil(pairs / 50),
               "n_samples": len(samples), "mae_s": round(mae, 1), "rmse_s": round(rmse, 1),
               "acc15": round(acc, 3), "f1": round(f1, 3), "iou50": round(iou, 3),
               "bnd_err_m": round(statistics.mean(berrs), 1) if berrs else None}
        print(f"{name:<18}{row['pairs']:>6}{row['requests']:>4}{row['mae_s']:>8}"
              f"{row['rmse_s']:>8}{row['acc15']:>7}{row['f1']:>6}{row['iou50']:>8}"
              f"{row['bnd_err_m'] or '-':>7}")
        return row

    print(f"射线二分:{n_ray} 对(16 向)")
    print(f"\n{'方法':<18}{'对数':>6}{'请求':>4}{'MAE_s':>8}{'RMSE':>8}{'acc15':>7}"
          f"{'F1':>6}{'IoU@50m':>8}{'边界Δm':>7}")
    rows = []

    def geo_inside(p, margin=0.75):
        d = math.hypot((p[0] - center[0]) * 111320,
                       (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
        brg = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
        return d < margin * r_at(brg)

    # 边界中点探针:相邻射线中角、半径取均值处
    mid_pts = []
    from core.coord import dest_at
    for i in range(16):
        b = (b16[i] + b16[(i + 1) % 16]) / 2 % 360
        rr = (r16[b16[i]] + r16[b16[(i + 1) % 16]]) / 2
        mid_pts.append(dest_at(center[1], center[0], b, rr))

    variants = []
    for tag, spacing, use_mid in (("M9a 射线+内200m", 200, False),
                                  ("M9c 射线+内200m+界中点", 200, True),
                                  ("M9b 射线+内400m", 400, False)):
        cand = [p for p in grid_points(center, spacing, 1000) if geo_inside(p)]
        extra = list(cand) + (mid_pts if use_mid else [])
        samples = dict(rays)
        for p in extra:
            k = key(p)
            if k in field:
                samples[k] = field[k]
        pairs = n_ray + len(cand) + (len(mid_pts) if use_mid else 0)
        print(f"  [{tag}] 内部 {len(cand)} 点 + 界中点 {len(mid_pts) if use_mid else 0}",
              file=sys.stderr)
        rows.append(evaluate(tag, samples, pairs))

    ap = os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4_analysis.json")
    data = json.load(open(ap, encoding="utf-8"))
    data["methods"] = [m for m in data["methods"] if not m["method"].startswith("M9")] + rows
    json.dump(data, open(ap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已追加至 e4_analysis.json")


if __name__ == "__main__":
    main()
