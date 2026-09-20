"""E10-X 补真值:为因预算跳过真值网格的城市补 250m 网格(81 对)并算指标。"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CITIES, CityRunner
from experiments.e4_sampling.run_e4 import grid_points, key

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900


def topup(idx):
    slug = CITIES[idx][0]
    p = os.path.join(_ROOT, "experiments", "results", "e10_boundary", f"e10x_{slug}.json")
    d = json.load(open(p, encoding="utf-8"))
    if d["metrics"].get("iou"):
        print(f"[{d['city']}] 已有指标,跳过")
        return
    center = tuple(d["center"])
    R = CityRunner(d["eid"], center, cap=R_used(d["eid"]) + 90)
    g = grid_points(center, 250, 1000)
    R.measure(g)
    truth = {}
    for q in g:
        row = R.cached(q)
        if row and row[0] is not None:
            truth[key(q)] = row[0]
    radii = {float(k): v for k, v in d["radii"].items()}
    keys = list(truth.keys())
    yt = [truth[k] <= TH for k in keys]
    yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
    inter = sum(1 for a, b in zip(yt, yp) if a and b)
    union = sum(1 for a, b in zip(yt, yp) if a or b)
    d["metrics"] = {"fp": sum(1 for a, b in zip(yt, yp) if b and not a),
                    "fn": sum(1 for a, b in zip(yt, yp) if a and not b),
                    "iou": round(inter / max(1, union), 3),
                    "truth_n": len(keys), "truth_spacing": 250}
    d["pairs_used"] = R_used(d["eid"])
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{d['city']}] FP={d['metrics']['fp']} FN={d['metrics']['fn']} "
          f"IoU={d['metrics']['iou']}(n={len(keys)}) | 累计 {d['pairs_used']} 对")


def R_used(eid):
    import sqlite3
    db = os.path.join(_ROOT, "experiments", "logs", "calls.db")
    with sqlite3.connect(db) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (eid,)).fetchone()[0]


if __name__ == "__main__":
    for i in [int(x) for x in (sys.argv[1:] or ["1", "3"])]:
        topup(i)
