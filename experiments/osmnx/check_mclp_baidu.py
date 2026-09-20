# -*- coding: utf-8 -*-
"""MCLPV - MCLP 选址的百度口径复核(OSM 参照网测时 vs 百度 matrix 实测)

对象:mclp_harbin.json 的 4 个选址(养老 k=1/2/3 + 教育 k=1)。
方法:养老需求格(818)固定种子抽 200 格,教育需求格(23)全测;
     每址 bc.routematrix(walking, [site], cells)(50 对/请求),
     覆盖=duration<=900s;与 OSM Dijkstra+吸附罚 的覆盖对比。
产出:results/osmnx/mclp_baidu_check.json;预算 ~623 对(EID=MCLPV)。
"""
import bisect
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import networkx as nx
import numpy as np
import osmnx as ox
from scipy.spatial import cKDTree

from core import baidu_client as bc
from core.coord import bd09_to_wgs84, dest_at

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
V_MS = 4.2 / 3.6
EID = "MCLPV"

city = json.load(open(os.path.join(ROOT, "experiments", "results", "e10_boundary",
                                   "e10x_harbin.json"), encoding="utf-8"))
mclp = json.load(open(os.path.join(ROOT, "experiments", "results", "osmnx",
                                   "mclp_harbin.json"), encoding="utf-8"))
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


G = ox.load_graphml(os.path.join(ROOT, "experiments", "logs", "osm_harbin.graphml"))
for _, _, _, d in G.edges(keys=True, data=True):
    d.setdefault("tt", d["length"] / V_MS)
ids = [n for n, _ in G.nodes(data=True)]
ns = np.array([(G.nodes[n]["y"], G.nodes[n]["x"]) for n in ids])
tree = cKDTree(ns)


def node_of(lat_w, lng_w):
    dd, i = tree.query([lat_w, lng_w])
    return ids[i], dd


cells = []
for i in range(-24, 25):
    lat0, lng0 = dest_at(center[1], center[0], 0, i * 50)
    for j in range(-24, 25):
        lat, lng = dest_at(lng0, lat0, 90, j * 50)
        d, b = polar((lat, lng))
        if d < r_at(b) - 20:
            cells.append((lat, lng))
cell_nodes = [node_of(*reversed(bd09_to_wgs84(p[1], p[0]))) for p in cells]
print(f"需求格 {len(cells)}(应 818)| 路网 {len(ids)} 节点")


def osm_cover(site_bd09):
    wlng, wlat = bd09_to_wgs84(site_bd09[1], site_bd09[0])
    n0, snap = node_of(wlat, wlng)
    reach = nx.single_source_dijkstra_path_length(G, n0, cutoff=TH - snap / V_MS, weight="tt")
    return {i for i, (nid, sn) in enumerate(cell_nodes)
            if nid in reach and reach[nid] + sn / V_MS <= TH}


def baidu_cover(site_bd09, idxs):
    """site -> cells[idxs] 逐 50 对请求,返回 duration<=900 的格集合。"""
    cov = set()
    for i in range(0, len(idxs), 50):
        chunk = idxs[i:i + 50]
        for attempt in range(4):
            r = bc.routematrix("walking", [tuple(site_bd09)],
                               [cells[k] for k in chunk], experiment_id=EID)
            if r.ok:
                break
            if r.status == 401 and attempt < 3:
                time.sleep([15, 30, 60][attempt])
                continue
            raise RuntimeError(f"matrix {r.status} {r.message}")
        for k, it in zip(chunk, bc.matrix_items(r)):
            if it.get("duration_s") is not None and it["duration_s"] <= TH:
                cov.add(k)
        time.sleep(0.3)
    return cov


rng = random.Random(7)
elderly_sample = sorted(rng.sample(range(len(cells)), 200))
out = {"community": "哈尔滨·道外", "elderly_sample_n": len(elderly_sample), "results": {}}

for pname in mclp["results"]:
    rows = mclp["results"][pname]
    sample = elderly_sample if pname.startswith("养老") else None
    if sample is None:  # 教育:需求格 = 23 个轻度盲格,重建
        poi = json.load(open(os.path.join(ROOT, "experiments", "results", "poi",
                                          "poi_harbin.json"), encoding="utf-8"))
        primary = [p for p in poi["pois"] if p["cat"] == "教育"]
        k_det = 1.31
        sample = sorted(i for i, p in enumerate(cells)
                        if min(math.hypot((p[0] - q["lat"]) * 111320,
                                          (p[1] - q["lng"]) * 111320
                                          * math.cos(math.radians(p[0]))) for q in primary)
                        * k_det / V_MS > TH)
    print(f"\n== {pname}: 复核样本 {len(sample)} 格 ==")
    osm_u, bd_u = set(), set()
    recs = []
    for row in rows:
        site = row["site_bd09"]
        oc = osm_cover(site) & set(sample)
        bdc = baidu_cover(site, sample)
        osm_u |= oc
        bd_u |= bdc
        recs.append({"k": row["k"], "site": site,
                     "osm_cov": len(oc), "baidu_cov": len(bdc),
                     "osm_cum_pct": round(100 * len(osm_u) / len(sample), 1),
                     "baidu_cum_pct": round(100 * len(bd_u) / len(sample), 1)})
        print(f"  k={row['k']} site({site[0]:.5f},{site[1]:.5f}) "
              f"OSM {len(oc)}/{len(sample)}({recs[-1]['osm_cum_pct']}%) | "
              f"百度 {len(bdc)}/{len(sample)}({recs[-1]['baidu_cum_pct']}%)")
    out["results"][pname] = {"sample_n": len(sample), "sites": recs,
                             "osm_total_pct": recs[-1]["osm_cum_pct"],
                             "baidu_total_pct": recs[-1]["baidu_cum_pct"]}

fp = os.path.join(ROOT, "experiments", "results", "osmnx", "mclp_baidu_check.json")
json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n已写入 {fp}")
