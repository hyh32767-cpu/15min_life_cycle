"""OSMnx 多城市推广:其余五社区 × {仪器标定 / 绝对精度 / 障碍先验 / 配置优化}

对象:北京B·东花市、上海·陆家嘴、广州·上下九、成都·九眼桥、哈尔滨·道外
(A·王府井已在 run_osmnx_truth.py 完成)

每城:
  ① 标定:该中心全部缓存实测点 T_api vs T_osm(MAE/偏差/r/分类一致率)
  ② 绝对精度:已存最终多边形 vs OSM 真值(重建真值格点作评估格),F1/IoU + 8 向边界Δ
  ③ 障碍先验:水系/河渠/铁路 × 最终多边形弦求交 vs 记录的弦违规/高ρ弦
  ④ 配置优化:OSM 预言机网格(射线×容差)→ 该城真值格上 F1,找最省配置
路网缓存:experiments/logs/osm_{slug}.graphml。产出:osmnx_cities.json
"""
import bisect
import json
import math
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString

from core.coord import bd09_to_wgs84, dest_at
from experiments.e4_sampling.run_e4 import cls_metrics, grid_points, key
from experiments.osmnx.run_osmnx_truth import OsmOracle, V_MS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
CITIES = [
    ("B", "e4_sampling/e4b.json", "北京B·东花市", 150, 1050),
    ("shanghai", "e10_boundary/e10x_shanghai.json", "上海·陆家嘴", None, 1000),
    ("guangzhou", "e10_boundary/e10x_guangzhou.json", "广州·上下九", None, 1000),
    ("chengdu", "e10_boundary/e10x_chengdu.json", "成都·九眼桥", None, 1000),
    ("harbin", "e10_boundary/e10x_harbin.json", "哈尔滨·道外", None, 1000),
]


def load_cached(center):
    db = os.path.join(ROOT, "experiments", "logs", "cache.db")
    out = {}
    with sqlite3.connect(db) as c:
        for d_lat, d_lng, dur in c.execute(
                "SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=?",
                (round(center[0], 6), round(center[1], 6))):
            if dur is not None:
                out[(d_lat, d_lng)] = dur
    return out


def get_graph(slug, center):
    gp = os.path.join(ROOT, "experiments", "logs", f"osm_{slug}.graphml")
    lng, lat = bd09_to_wgs84(center[1], center[0])
    if os.path.exists(gp):
        G = ox.load_graphml(gp)
    else:
        mirrors = [None,
                   "https://overpass.kumi.systems/api/interpreter",
                   "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                   "https://overpass.osm.jp/api/interpreter"]
        last = None
        for m in mirrors:
            try:
                ox.settings.requests_timeout = 120
                if m:
                    ox.settings.overpass_url = m
                print(f"  下载路网({'镜像 ' + m.split('/')[2] if m else '官方'})…")
                G = ox.graph.graph_from_point((lat, lng), dist=1600, network_type="walk")
                break
            except Exception as e:
                last = e
                print(f"  失败:{str(e)[:60]}")
        else:
            raise RuntimeError(f"全部 Overpass 端点失败:{str(last)[:80]}")
        ox.save_graphml(G, gp)
    for u, v, k, d in G.edges(keys=True, data=True):
        if "tt" not in d:
            d["tt"] = d["length"] / V_MS
    return G


def r_at(brg, radii):
    ks = sorted(radii)
    i = bisect.bisect_right(ks, brg) - 1
    b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
    db = (b1 - b0) % 360 or 360
    t = ((brg - b0) % 360) / db
    return radii[b0] * (1 - t) + radii[b1] * t


def in_poly(p, center, radii):
    d = math.hypot((p[0] - center[0]) * 111320,
                   (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
    b = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
    return d < r_at(b, radii)


def run_city(slug, fname, label, spacing, half):
    d = json.load(open(os.path.join(ROOT, "experiments", "results", fname), encoding="utf-8"))
    center = tuple(d["center"])
    rk = "radii" if "radii" in d else "radii_final"
    radii = {float(k): v for k, v in d[rk].items()}
    viol = set(round(v, 1) for v in d.get("chord_violations", []))
    hot = set(round(v, 1) for v in d.get("rho", {}).get("hot_chords", []))
    if spacing is None:
        spacing = d.get("metrics", {}).get("truth_spacing")
    print(f"\n===== {label} =====")
    G = get_graph(slug, center)
    print(f"路网 {len(G.nodes)} 节点")
    O = OsmOracle(G, center)
    cached = load_cached(center)

    # ① 标定
    pairs = []
    for p, ta in cached.items():
        wlng, wlat = bd09_to_wgs84(p[1], p[0])
        to = O.t_of(wlat, wlng)
        if math.isfinite(to):
            pairs.append((ta, to))
    errs = [b - a for a, b in pairs]
    r = float(np.corrcoef([a for a, _ in pairs], [b for _, b in pairs])[0, 1])
    agree = float(np.mean([(a <= TH) == (b <= TH) for a, b in pairs]))
    cal = {"n": len(pairs), "mae_s": round(float(np.mean(np.abs(errs)))),
           "bias_s": round(float(np.mean(errs))), "r": round(r, 3),
           "cls_agree": round(agree, 3)}
    print(f"① 标定:n={cal['n']} MAE={cal['mae_s']}s 偏差={cal['bias_s']:+d}s r={cal['r']}"
          f" 一致率={cal['cls_agree']}")

    # ② 绝对精度(重建真值格点)
    lat_out = {"calibration": cal}
    if spacing:
        g = grid_points(center, spacing, half)
        lat_keys = [key(p) for p in g]
        y_osm, y_pred = [], []
        for p in g:
            wlng, wlat = bd09_to_wgs84(p[1], p[0])
            y_osm.append(O.t_of(wlat, wlng) <= TH)
            y_pred.append(in_poly(p, center, radii))
        acc, prec, rec, f1 = cls_metrics(y_osm, y_pred)
        inter = sum(1 for a, b in zip(y_osm, y_pred) if a and b)
        union = sum(1 for a, b in zip(y_osm, y_pred) if a or b)
        bnd = {}
        for b in range(0, 360, 45):
            r_api = r_at(b, radii)
            last = None
            for dd in range(200, 1401, 10):
                p = dest_at(center[1], center[0], b, dd)
                wlng, wlat = bd09_to_wgs84(p[1], p[0])
                if O.t_of(wlat, wlng) > TH:
                    last = dd - 5
                    break
            bnd[b] = (round(r_api), last or 1400)
        diffs = [abs(a - b_) for a, b_ in bnd.values()]
        lat_out["absolute"] = {"n": len(y_osm), "f1": round(f1, 3), "iou": round(inter / union, 3),
                               "bnd_mean_m": round(float(np.mean(diffs))),
                               "bnd_max_m": round(max(diffs)),
                               "per_bearing": {str(b): v for b, v in bnd.items()}}
        print(f"② 绝对精度:F1={f1:.3f} IoU={inter/union:.3f} 边界Δ均值{np.mean(diffs):.0f}m"
              f"(max {max(diffs)}m)")
    else:
        print("② 无真值格点记录,跳过")

    # ③ 障碍先验
    prior = {}
    try:
        lng, lat = bd09_to_wgs84(center[1], center[0])
        geoms = []
        for tags in ({"natural": ["water", "wetland"]},
                     {"waterway": ["river", "canal", "stream"]},
                     {"railway": "rail"}):
            try:
                f = ox.features.features_from_point((lat, lng), dist=1500, tags=tags)
                geoms += [g for g in f.geometry if g is not None and not g.is_empty]
            except Exception:
                pass
        ks = sorted(radii)
        flagged = set()
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            mb = round(((a + b) / 2) % 360, 1)
            p1 = dest_at(center[1], center[0], a % 360, radii[a % 360])
            p2 = dest_at(center[1], center[0], b % 360, radii[b % 360])
            w1 = bd09_to_wgs84(p1[1], p1[0])
            w2 = bd09_to_wgs84(p2[1], p2[0])
            seg = LineString([(w1[0], w1[1]), (w2[0], w2[1])])
            if any(seg.intersects(g) for g in geoms):
                flagged.add(mb)
        prior = {"flagged": sorted(flagged), "n_viol": len(viol), "n_hot": len(hot),
                 "hit_viol": len(flagged & viol), "hit_hot": len(flagged & hot)}
        print(f"③ 障碍先验:标记 {sorted(flagged)} | 命中违规 {prior['hit_viol']}/{len(viol)}"
              f" 命中高ρ {prior['hit_hot']}/{len(hot)}")
    except Exception as e:
        prior = {"error": str(e)[:80]}
        print("③ 失败:", prior["error"])
    lat_out["barrier_prior"] = prior

    # ④ 配置优化(仅在有真值格点时)
    if spacing:
        grid, best = [], None
        osm_y = y_osm
        for n_rays in (8, 12, 16, 24):
            for tol in (15, 30, 50):
                bearings = [i * 360 / n_rays for i in range(n_rays)]
                rr, calls = {}, 0
                for b in bearings:
                    lo, hi = 200.0, 1400.0
                    def probe(bb, dd):
                        nonlocal calls
                        calls += 1
                        p = dest_at(center[1], center[0], bb, dd)
                        wlng, wlat = bd09_to_wgs84(p[1], p[0])
                        return O.t_of(wlat, wlng)
                    probe(b, 800)
                    while hi - lo > tol:
                        m = (lo + hi) / 2
                        t = probe(b, m)
                        if t <= TH:
                            lo = m
                        else:
                            hi = m
                    rr[b] = (lo + hi) / 2
                yp = [in_poly(p, center, rr) for p in g]
                _, _, _, f1v = cls_metrics(osm_y, yp)
                iouv = (sum(1 for a, b2 in zip(osm_y, yp) if a and b2) /
                        max(1, sum(1 for a, b2 in zip(osm_y, yp) if a or b2)))
                grid.append({"rays": n_rays, "tol_m": tol, "probes": calls,
                             "f1": round(f1v, 3), "iou": round(iouv, 3)})
        ok = [x for x in grid if x["f1"] >= 0.97]
        best = min(ok, key=lambda x: x["probes"]) if ok else None
        lat_out["config_grid"] = grid
        lat_out["config_best"] = best
        if best:
            print(f"④ 最省配置(F1≥0.97):{best['rays']}向×{best['tol_m']}m = {best['probes']}探针"
                  f"(F1 {best['f1']})")
        else:
            top = max(grid, key=lambda x: x["f1"])
            print(f"④ 无配置达 0.97;最好 {top}")
    return lat_out


def main():
    only = set(sys.argv[1:])
    out = {}
    for slug, fname, label, spacing, half in CITIES:
        if only and slug not in only:
            continue
        try:
            out[label] = run_city(slug, fname, label, spacing, half)
        except Exception as e:
            out[label] = {"error": str(e)[:150]}
            print(f"[{label}] 失败:{out[label]['error']}")
    prev_path = os.path.join(ROOT, "experiments", "results", "osmnx", "osmnx_cities.json")
    if os.path.exists(prev_path):
        prev = json.load(open(prev_path, encoding="utf-8"))
        prev.update(out)
        out = prev
    json.dump(out, open(prev_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/osmnx_cities.json")


if __name__ == "__main__":
    main()
