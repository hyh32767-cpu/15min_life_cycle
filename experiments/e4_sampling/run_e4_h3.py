"""E4-H3 · H3 六边形多分辨率采样(AMR)—— 设计文档 05 的正统实现

流程:
  1) 粗扫:H3 res9(边长 ~201m)grid_disk 覆盖中心 ~1.4km,测各六边形中心步行时长
  2) 加密:12–18min(720–1080s)边界带六边形 → cell_to_children 细分到 res10(边长 ~76m),
     只测子六边形中心;子仍在带内且预算允许时再细一轮(≤ res11)
  3) 样本集 = 全部已测六边形中心(bd09),同一口径评估(MAE/acc15/F1/IoU/边界Δ)

坐标系:H3 基于 WGS84,测时与评估均在 bd09 空间 —— 入口 wgs84→bd09,出口统一 bd09。
评估基准:eval_setup.json(与 M1–M8 完全同口径的 80 留出点 + 50m 格点真值 + 参考边界)。
预算:≤ 400 对。产出:追加行至 e4_analysis.json;控制台杀手表。
"""
import json
import math
import os
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import h3

from core import baidu_client as bc
from core import cache
from core.coord import wgs84_to_bd09
from experiments.e4_sampling.run_e4 import boundary_radius, cls_metrics, idw, key

EID = "E4H3"
PAIRS_BUDGET = 400
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES_COARSE, RES_FINE, RES_EXTRA = 9, 10, 11
BAND = (720, 1080)                    # 12–18 min
TH = 900
PACE = 1.2


def pairs_used():
    db = os.path.join(_ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (EID,)).fetchone()[0]


def cell_center_bd09(cell):
    lat, lng = h3.cell_to_latlng(cell)          # WGS84
    dlng, dlat = wgs84_to_bd09(lng, lat)        # 返回 (lng, lat) 顺序
    return (dlat, dlng)                          # (lat, lng) bd09


def measure_cells(S_center, cells, log):
    """测一批六边形中心(去缓存、50 对/请求、限流退避),返回 {(lat,lng): T}。"""
    todo = [c for c in cells if cache.get(S_center, cell_center_bd09(c)) is None]
    out = {}
    pts = [cell_center_bd09(c) for c in todo]
    for i in range(0, len(pts), 50):
        chunk = pts[i:i + 50]
        if pairs_used() + len(chunk) >= PAIRS_BUDGET:
            print("  ⚠️ 对数预算触顶,截断本批")
            break
        for attempt in range(4):
            r = bc.routematrix("walking", [S_center], chunk, experiment_id=EID)
            if r.ok:
                break
            if r.status == 401 and attempt < 3:
                w = [15, 30, 60][attempt]
                print(f"  ⚠️ 401 退避 {w}s")
                time.sleep(w)
                continue
            raise RuntimeError(f"matrix failed {r.status} {r.message}")
        for p, it in zip(chunk, bc.matrix_items(r)):
            cache.put(S_center, p, it["duration_s"], it["distance_m"])
            out[key(p)] = it["duration_s"]
        log[0] += 1
        time.sleep(PACE)
    for c in cells:
        row = cache.get(S_center, cell_center_bd09(c))
        if row:
            out[key(cell_center_bd09(c))] = row[0]
    return out


def main():
    setup = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"), encoding="utf-8"))
    center = tuple(setup["center"])
    print(f"中心(bd09): {center[0]:.5f},{center[1]:.5f}")
    print(f"H3 分辨率:粗 res{RES_COARSE}(边{h3.average_hexagon_edge_length(RES_COARSE, unit='m'):.0f}m)"
          f" → 加密 res{RES_FINE}(边{h3.average_hexagon_edge_length(RES_FINE, unit='m'):.0f}m)"
          f" → 深加密 res{RES_EXTRA}")

    # H3 用 WGS84:中心 bd09 → wgs84
    from core.coord import bd09_to_wgs84
    wlng, wlat = bd09_to_wgs84(center[1], center[0])
    origin_cell = h3.latlng_to_cell(wlat, wlng, RES_COARSE)
    coarse_cells = list(h3.grid_disk(origin_cell, 4))       # ~1.4km 覆盖,61 格
    print(f"== 粗扫 res{RES_COARSE}:{len(coarse_cells)} 格 ==")
    req = [0]
    S = measure_cells(center, coarse_cells, req)
    n1 = pairs_used()
    print(f"  完成,累计 {n1} 对 / {req[0]} 请求")

    # 边界带加密
    band_cells = [c for c in coarse_cells
                  if (t := S.get(key(cell_center_bd09(c)))) is not None and BAND[0] <= t <= BAND[1]]
    fine_cells = []
    for c in band_cells:
        fine_cells += list(h3.cell_to_children(c, RES_FINE))
    print(f"== 加密 res{RES_FINE}:边界带 {len(band_cells)} 格 → 子格 {len(fine_cells)} ==")
    S.update(measure_cells(center, fine_cells, req))
    n2 = pairs_used()
    print(f"  完成,累计 {n2} 对 / {req[0]} 请求")

    # 深加密:子格仍在带内(且未触预算)
    deep_band = [c for c in fine_cells
                 if (t := S.get(key(cell_center_bd09(c)))) is not None and BAND[0] <= t <= BAND[1]]
    deep_cells = []
    for c in deep_band[:18]:                               # 上限 18 格 × 7 子 = 126 对
        deep_cells += list(h3.cell_to_children(c, RES_EXTRA))
    if deep_cells and pairs_used() + len(deep_cells) < PAIRS_BUDGET:
        print(f"== 深加密 res{RES_EXTRA}:带内子格 {len(deep_band)} → 取 {len(deep_band[:18])} 格 "
              f"→ {len(deep_cells)} 子格 ==")
        S.update(measure_cells(center, deep_cells, req))
    total_pairs = pairs_used()
    print(f"采样总计:{total_pairs} 对 / {req[0]} 请求(含缓存命中复用)")

    # ---- 同口径评估 ----
    val = [tuple(v) for v in setup["val"]]
    val_true = setup["val_true"]
    lat50 = [tuple(v) for v in setup["lat50"]]
    truth50 = setup["truth50"]
    ref_bnd = {int(b): v for b, v in setup["ref_boundaries_m"].items()}

    pv = idw(S, val)
    pairs = [(a, b) for a, b in zip(val_true, pv) if a is not None and b is not None]
    err = [b - a for a, b in pairs]
    mae = statistics.mean(abs(e) for e in err)
    rmse = math.sqrt(statistics.mean(e * e for e in err))
    acc, prec, rec, f1 = cls_metrics([a <= TH for a, _ in pairs], [b <= TH for _, b in pairs])
    pg = idw(S, lat50)
    yg = [p is not None and p <= TH for p in pg]
    inter = sum(1 for a, b in zip(truth50, yg) if a and b)
    union = sum(1 for a, b in zip(truth50, yg) if a or b)
    iou = inter / max(1, union)
    berrs = [abs(boundary_radius(center, S, b) - ref_bnd[b]) for b in range(0, 360, 45)
             if ref_bnd[b] and boundary_radius(center, S, b)]
    row = {"method": f"MH H3 AMR r{RES_COARSE}→{RES_EXTRA}", "pairs": total_pairs,
           "requests": req[0], "n_samples": len(S), "mae_s": round(mae, 1),
           "rmse_s": round(rmse, 1), "acc15": round(acc, 3), "f1": round(f1, 3),
           "iou50": round(iou, 3),
           "bnd_err_m": round(statistics.mean(berrs), 1) if berrs else None}
    print("\n===== H3 行 =====")
    print(f"{'方法':<22}{'对数':>6}{'请求':>4}{'MAE_s':>7}{'RMSE':>7}{'acc15':>7}"
          f"{'F1':>6}{'IoU@50m':>8}{'边界Δm':>7}")
    print(f"{row['method']:<22}{row['pairs']:>6}{row['requests']:>4}{row['mae_s']:>7}"
          f"{row['rmse_s']:>7}{row['acc15']:>7}{row['f1']:>6}{row['iou50']:>8}"
          f"{row['bnd_err_m'] or '-':>7}")

    # 追加进 e4_analysis.json
    ap = os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4_analysis.json")
    data = json.load(open(ap, encoding="utf-8"))
    data["methods"] = [m for m in data["methods"] if not m["method"].startswith("MH")] + [row]
    json.dump(data, open(ap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已追加至 e4_analysis.json")


if __name__ == "__main__":
    main()
