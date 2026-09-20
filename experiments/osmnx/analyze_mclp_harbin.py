"""MCLP 选址处方 —— 哈尔滨·道外 养老/教育设施(零 API,OSM 步行网测时)

问题:盲区已定位(养老全盲、教育 23 格轻度)→ 新设施放哪覆盖最大?
方法(Church & ReVelle 1974 最大覆盖,贪心近似):
  需求格 = 等时圈内 50m 格(养老:全部;教育:到最近小学>15min 的格)
  候选点 = 圈内 100m 格心
  覆盖判定 = 候选点→需求格 的 OSM 路网 Dijkstra 步行时长 ≤ 900s(含吸附罚项)
  贪心选 k=1,2,3,报告 Before/After 覆盖率与选址坐标(bd09)。
诚实口径:百度配额已尽,测时用 OSM 参照网(仪器一致性 r=0.309/形一致 F1 0.933);
产品化时换成百度 matrix(origin=候选点)即可,框架不变。
产出:experiments/results/mclp_harbin.json
"""
import bisect
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import networkx as nx
import numpy as np
import osmnx as ox

from core.coord import bd09_to_wgs84, dest_at, wgs84_to_bd09
from experiments.e4_sampling.run_e4 import grid_points

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
V_MS = 4.2 / 3.6


def main():
    city = json.load(open(os.path.join(ROOT, "experiments", "results",
                                       "e10_boundary", "e10x_harbin.json"), encoding="utf-8"))
    poi = json.load(open(os.path.join(ROOT, "experiments", "results", "poi", "poi_harbin.json"), encoding="utf-8"))
    center = tuple(city["center"])
    radii = {float(k): v for k, v in city["radii"].items()}
    ks = sorted(radii)

    def r_at(brg):
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    def polar(p):
        d = math.hypot((p[0] - center[0]) * 111320,
                       (p[1] - center[1]) * 111320 * math.cos(math.radians(center[0])))
        b = math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360
        return d, b

    # ---- 图与节点索引 ----
    G = ox.load_graphml(os.path.join(ROOT, "experiments", "logs", "osm_harbin.graphml"))
    for u, v, k, d in G.edges(keys=True, data=True):
        if "tt" not in d:
            d["tt"] = d["length"] / V_MS
    ids = [n for n, _ in G.nodes(data=True)]
    ns = np.array([(G.nodes[n]["y"], G.nodes[n]["x"]) for n in ids])
    import scipy.spatial
    tree = scipy.spatial.cKDTree(ns)

    def node_of(lat_w, lng_w):
        d, i = tree.query([lat_w, lng_w])
        return ids[i], d

    def cover_set(cand_bd09):
        """候选点 15min 可达的需求格集合(OSM Dijkstra + 吸附罚项)。"""
        wlng, wlat = bd09_to_wgs84(cand_bd09[1], cand_bd09[0])
        n0, snap = node_of(wlat, wlng)
        reach = nx.single_source_dijkstra_path_length(G, n0, cutoff=TH - snap / V_MS,
                                                      weight="tt")
        out = []
        for idx, (nid, sn) in cell_nodes.items():
            if nid in reach and reach[nid] + sn / V_MS <= TH:
                out.append(idx)
        return set(out)

    # ---- 需求格与候选 ----
    cells = []
    for i in range(-24, 25):
        lat0, lng0 = dest_at(center[1], center[0], 0, i * 50)
        for j in range(-24, 25):
            lat, lng = dest_at(lng0, lat0, 90, j * 50)
            d, b = polar((lat, lng))
            if d < r_at(b) - 20:
                cells.append((lat, lng))
    cell_nodes = {}
    for idx, p in enumerate(cells):
        wlng, wlat = bd09_to_wgs84(p[1], p[0])
        nid, sn = node_of(wlat, wlng)
        cell_nodes[idx] = (nid, sn)
    cands = []
    for i in range(-12, 13):
        lat0, lng0 = dest_at(center[1], center[0], 0, i * 100)
        for j in range(-12, 13):
            lat, lng = dest_at(lng0, lat0, 90, j * 100)
            d, b = polar((lat, lng))
            if d < r_at(b) - 20:
                cands.append((lat, lng))
    print(f"需求格 {len(cells)} | 候选点 {len(cands)} | 路网 {len(ids)} 节点")

    primary = [p for p in poi["pois"] if p["cat"] == "教育"]
    k_det = 1.31

    def edu_blind(p):
        if not primary:
            return True
        tmin = min(math.hypot((p[0] - q["lat"]) * 111320,
                              (p[1] - q["lng"]) * 111320 * math.cos(math.radians(p[0])))
                   for q in primary) * k_det / V_MS
        return tmin > TH

    problems = {
        "养老(全盲)": set(range(len(cells))),
        "教育(轻度盲区)": {i for i, p in enumerate(cells) if edu_blind(p)},
    }
    out = {}
    for name, demand in problems.items():
        print(f"\n== {name}:需求格 {len(demand)} ==")
        covers = [cover_set(c) & demand for c in cands]
        chosen, cov = [], set()
        for k in (1, 2, 3):
            best_i, best_gain = None, 0
            for i, cs in enumerate(covers):
                gain = len(cs - cov)
                if gain > best_gain:
                    best_i, best_gain = i, gain
            if best_i is None:
                break
            chosen.append(best_i)
            cov |= covers[best_i]
            pct = len(cov) / max(1, len(demand)) * 100
            c = cands[best_i]
            print(f"  选址{k}:({c[0]:.5f},{c[1]:.5f}) bd09 | 累计覆盖 {len(cov)}/{len(demand)}"
                  f" = {pct:.0f}%")
            out.setdefault(name, []).append({
                "k": k, "site_bd09": [round(c[0], 6), round(c[1], 6)],
                "covered": len(cov), "demand": len(demand), "coverage_pct": round(pct)})
    json.dump({"community": "哈尔滨·道外", "cells": len(cells), "cands": len(cands),
               "network": "OSM walk (参照)", "results": out},
              open(os.path.join(ROOT, "experiments", "results", "osmnx", "mclp_harbin.json"),
                   "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 mclp_harbin.json")


if __name__ == "__main__":
    main()
