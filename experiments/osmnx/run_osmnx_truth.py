"""OSMnx 独立真值实验 —— 仪器标定 / 绝对精度 / 障碍先验 / 采样配置优化(零 API 配额)

运行环境:uv venv(.venv,Python 3.12 + osmnx 2.1.1 + scipy)

  ① 仪器标定:社区 A 80 留出点上,T_api vs T_osmnx(Dijkstra,4.2km/h)
     → MAE / 偏差 / 相关系数:OSM 网络作为"第二台仪器"与百度的一致度
  ② 绝对精度:我们的方法(16 边形 / 射线+Delaunay)对 OSM 真值的分类精度
     → 此前所有精度都是"对 API 自测",现在是第三方独立参照
  ③ 障碍先验:OSM 水系/铁路/屏障要素 × 弦求交 → 能否零 API 预测 E10 的复杂扇区
  ④ 采样配置优化:用 OSM 当预言机,网格搜索(射线数 × 二分容差)→ F1-调用数曲线,
     找"最少 API 调用达标 F1≥0.97"的配置

产出:experiments/results/osmnx_truth.json + 控制台报告
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import LineString, Point

from core.coord import bd09_to_wgs84, dest_at
from experiments.e4_sampling.run_e4 import cls_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
V_MS = 4.2 / 3.6

A = json.load(open(os.path.join(ROOT, "experiments", "results", "e4_sampling", "e4.json"), encoding="utf-8"))
A_CENTER = tuple(A["center"])
A_RADII16 = {float(k): v for k, v in A["m4_radii"].items()}
SETUP = json.load(open(os.path.join(ROOT, "experiments", "results", "e4_sampling", "eval_setup.json"),
                       encoding="utf-8"))
B = json.load(open(os.path.join(ROOT, "experiments", "results", "e4_sampling", "e4b.json"), encoding="utf-8"))
B_CENTER = tuple(B["center"])
B_ALL = {float(k): v for k, v in B["radii_final"].items()}
B_RADII16 = {b: B_ALL[b] for b in sorted(B_ALL) if b in {i * 22.5 for i in range(16)}}
B_VIOL = {33.8, 56.2, 146.2, 168.8, 191.2, 213.8, 258.8, 281.2, 348.8}
A_VIOL = {33.8, 191.2}
A_HOT_RHO = {78.8, 101.2, 236.2, 258.8, 326.2, 348.8}      # E10-C ρ>2
B_HOT_RHO = {11.2, 78.8, 123.8, 326.2}


def get_graph(center_bd09, dist=1600):
    lng, lat = bd09_to_wgs84(center_bd09[1], center_bd09[0])
    ox.settings.requests_timeout = 90
    G = ox.graph.graph_from_point((lat, lng), dist=dist, network_type="walk")
    for u, v, k, d in G.edges(keys=True, data=True):
        d["tt"] = d["length"] / V_MS
    return G, (lat, lng)


class OsmOracle:
    """以 OSMnx Dijkstra 为预言机的 T(center→p) 估计(节点时间 + 吸附罚项)。"""

    def __init__(self, G, center_bd09):
        self.G = G
        import scipy.spatial
        self.ids = [n for n, _ in G.nodes(data=True)]
        ns = np.array([(G.nodes[n]["y"], G.nodes[n]["x"]) for n in self.ids])
        self.tree = scipy.spatial.cKDTree(ns)
        lng, lat = bd09_to_wgs84(center_bd09[1], center_bd09[0])
        src = ox.distance.nearest_nodes(G, X=lng, Y=lat)
        self.dist = nx.single_source_dijkstra_path_length(G, src, weight="tt", cutoff=2500)

    def t_of(self, lat, lng):
        d, i = self.tree.query([lat, lng])
        node_time = self.dist.get(self.ids[i], math.inf)
        return node_time + d / V_MS


def main():
    out = {}
    # ---------- 图下载 ----------
    print("下载社区 A(王府井)步行路网 1.6km …")
    GA, _ = get_graph(A_CENTER)
    OA = OsmOracle(GA, A_CENTER)
    print(f"  节点 {len(GA.nodes)} 边 {len(GA.edges)},Dijkstra 可达 {len(OA.dist)} 节点")

    # ---------- ① 仪器标定 ----------
    print("\n== ① 仪器标定:API vs OSMnx(80 留出点)==")
    val = [tuple(v) for v in SETUP["val"]]
    val_true = SETUP["val_true"]
    osm_ts, pairs = [], []
    for p, ta in zip(val, val_true):
        wlng, wlat = bd09_to_wgs84(p[1], p[0])
        to = OA.t_of(wlat, wlng)
        osm_ts.append(to)
        if ta is not None and math.isfinite(to):
            pairs.append((ta, to))
    errs = [b - a for a, b in pairs]
    mae = float(np.mean(np.abs(errs)))
    bias = float(np.mean(errs))
    r = float(np.corrcoef([a for a, _ in pairs], [b for _, b in pairs])[0, 1])
    cls_agree = float(np.mean([(a <= TH) == (b <= TH) for a, b in pairs]))
    print(f"  MAE={mae:.0f}s 偏差(API−OSM)={bias:+.0f}s 相关系数 r={r:.3f} 15min分类一致率={cls_agree:.3f}")
    out["calibration"] = {"mae_s": round(mae), "bias_s": round(bias), "pearson_r": round(r, 3),
                          "cls_agree": round(cls_agree, 3), "n": len(pairs)}

    # ---------- ② 绝对精度(50m 格点 vs OSM 真值)----------
    print("\n== ② 绝对精度(对 OSM 真值)==")
    lat50 = [tuple(v) for v in SETUP["lat50"]]
    osm_y = []
    for p in lat50:
        wlng, wlat = bd09_to_wgs84(p[1], p[0])
        osm_y.append(OA.t_of(wlat, wlng) <= TH)

    # 我们的方法:16 边形
    import bisect

    def r_at(brg, radii):
        ks = sorted(radii)
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    def in_poly(p, radii):
        d = math.hypot((p[0] - A_CENTER[0]) * 111320,
                       (p[1] - A_CENTER[1]) * 111320 * math.cos(math.radians(A_CENTER[0])))
        b = math.degrees(math.atan2(p[1] - A_CENTER[1], p[0] - A_CENTER[0])) % 360
        return d < r_at(b, radii)

    yp = [in_poly(p, A_RADII16) for p in lat50]
    acc, prec, rec, f1 = cls_metrics(osm_y, yp)
    inter = sum(1 for a, b in zip(osm_y, yp) if a and b)
    union = sum(1 for a, b in zip(osm_y, yp) if a or b)
    print(f"  16边形 vs OSM:acc={acc:.3f} F1={f1:.3f} IoU={inter/union:.3f}")
    out["absolute_16gon"] = {"acc": round(acc, 3), "f1": round(f1, 3),
                             "iou": round(inter / union, 3)}

    # 边界半径对比(8 主方向)
    bnd_api, bnd_osm = {}, {}
    for b in range(0, 360, 45):
        bnd_api[b] = r_at(b, A_RADII16)
        last = None
        for d in range(200, 1401, 10):
            p = dest_at(A_CENTER[1], A_CENTER[0], b, d)
            wlng, wlat = bd09_to_wgs84(p[1], p[0])
            if OA.t_of(wlat, wlng) > TH:
                last = d - 5
                break
        bnd_osm[b] = last or 1400
    diffs = [abs(bnd_api[b] - bnd_osm[b]) for b in bnd_api]
    print(f"  边界半径:API多边形 vs OSM 平均|Δ|={np.mean(diffs):.0f}m(max {max(diffs):.0f}m)")
    out["boundary_api_vs_osm"] = {"mean_abs_m": round(float(np.mean(diffs))),
                                  "per_bearing": {str(b): [round(bnd_api[b]), round(bnd_osm[b])]
                                                  for b in bnd_api}}

    # ---------- ③ 障碍先验 ----------
    print("\n== ③ 障碍先验:OSM 水系/铁路能否预测复杂扇区 ==")
    def barrier_chords(center, radii16, tags, dist=1500):
        try:
            f = ox.features.features_from_point(
                (bd09_to_wgs84(center[1], center[0])[1],
                 bd09_to_wgs84(center[1], center[0])[0]), dist=dist, tags=tags)
        except Exception as e:
            print(f"    features 获取失败:{str(e)[:80]}")
            return {}
        print(f"    [{cname}·{tag_name}] 要素 {len(f)} 条")
        hits = {}
        for (i, row) in f.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            ks = sorted(radii16)
            for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
                mb = round(((a + b) / 2) % 360, 1)
                p1 = dest_at(center[1], center[0], a % 360, radii16[a % 360])
                p2 = dest_at(center[1], center[0], b % 360, radii16[b % 360])
                w1 = bd09_to_wgs84(p1[1], p1[0])
                w2 = bd09_to_wgs84(p2[1], p2[0])
                seg = LineString([(w1[0], w1[1]), (w2[0], w2[1])])
                try:
                    if seg.intersects(geom):
                        hits.setdefault(mb, set()).add(str(i[0]) if isinstance(i, tuple) else str(i))
                except Exception:
                    pass
        return hits

    for tag_name, tags in (("水系", {"natural": ["water", "wetland"]}),
                           ("河渠", {"waterway": ["river", "canal", "stream"]}),
                           ("铁路", {"railway": "rail"}),
                           ("屏障", {"barrier": ["city_wall", "wall", "fence"]})):
        for cname, center, radii16, viol, hot in (
                ("A", A_CENTER, A_RADII16, A_VIOL, A_HOT_RHO),
                ("B", B_CENTER, B_RADII16, B_VIOL, B_HOT_RHO)):
            hits = barrier_chords(center, radii16, tags)
            flagged = set(hits)
            pv = len(flagged & viol)
            ph = len(flagged & hot)
            print(f"  [{cname}·{tag_name}] 弦穿越 {sorted(flagged)} | 命中违规 {pv}/{len(viol)}"
                  f" 命中高ρ {ph}/{len(hot)}")
            out.setdefault("barrier_prior", {}).setdefault(cname, {})[tag_name] = {
                "flagged": sorted(flagged), "hit_violations": pv, "hit_hot_rho": ph}

    # ---------- ④ 采样配置优化(OSM 预言机网格搜索)----------
    print("\n== ④ 采样配置优化(预言机 = OSM,目标 F1≥0.97)==")
    print(f"{'射线数':>5}{'容差m':>6}{'探针数':>6}{'F1':>7}{'IoU':>7}")
    grid = []
    for n_rays in (8, 12, 16, 24):
        for tol in (15, 30, 50):
            bearings = [i * 360 / n_rays for i in range(n_rays)]
            radii = {}
            calls = 0

            def probe(b, d):
                nonlocal calls
                calls += 1
                p = dest_at(A_CENTER[1], A_CENTER[0], b, d)
                wlng, wlat = bd09_to_wgs84(p[1], p[0])
                return OA.t_of(wlat, wlng)

            for b in bearings:
                lo, hi = 200.0, 1400.0
                t = probe(b, 800)
                while hi - lo > tol:
                    m = (lo + hi) / 2
                    t = probe(b, m)
                    if t <= TH:
                        lo = m
                    else:
                        hi = m
                radii[b] = (lo + hi) / 2
            yp2 = [in_poly_r(p, radii) for p in lat50]
            if n_rays in (8, 16) and tol == 15:
                print(f"    [diag] radii范围 {min(radii.values()):.0f}-{max(radii.values()):.0f}m"
                      f" 预测正类 {sum(yp2)} 真值正类 {sum(osm_y)}")
            _, _, _, f1v = cls_metrics(osm_y, yp2)
            iou2 = (sum(1 for a, b in zip(osm_y, yp2) if a and b) /
                    max(1, sum(1 for a, b in zip(osm_y, yp2) if a or b)))
            grid.append({"rays": n_rays, "tol_m": tol, "probes": calls,
                         "f1": round(f1v, 3), "iou": round(iou2, 3)})
            print(f"{n_rays:>5}{tol:>6}{calls:>6}{f1v:>7.3f}{iou2:>7.3f}")
    ok = [g for g in grid if g["f1"] >= 0.97]
    best = min(ok, key=lambda g: g["probes"]) if ok else None
    print(f"  最省配置(F1≥0.97):{best}")
    out["config_grid"] = grid
    out["config_best"] = best

    json.dump(out, open(os.path.join(ROOT, "experiments", "results", "osmnx", "osmnx_truth.json"),
                        "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/osmnx_truth.json")


def in_poly_r(p, radii):
    import bisect
    d = math.hypot((p[0] - A_CENTER[0]) * 111320,
                   (p[1] - A_CENTER[1]) * 111320 * math.cos(math.radians(A_CENTER[0])))
    b = math.degrees(math.atan2(p[1] - A_CENTER[1], p[0] - A_CENTER[0])) % 360
    ks = sorted(radii)
    i = bisect.bisect_right(ks, b) - 1
    b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
    db = (b1 - b0) % 360 or 360
    t = ((b - b0) % 360) / db
    rr = radii[b0] * (1 - t) + radii[b1] * t
    return d < rr


if __name__ == "__main__":
    main()
