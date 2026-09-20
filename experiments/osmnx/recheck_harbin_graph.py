# -*- coding: utf-8 -*-
"""哈尔滨 OSM 路网复核(TODO P1):943 节点疑似偏稀,多端点重下对比。

道外棚改区可能真实稀疏,也可能是当时限流截断——重下见分晓。
仅 Overpass(免费),零百度配额。若显著更密:存 osm_harbin_v2.graphml(不直接覆盖,
MCLP 已按现图+百度复核定稿;新图供地图底图/OSMnx 参照线升级用)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import osmnx as ox

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CENTER_WGS = (45.78274, 126.64187)   # 道外中心(bd09 45.78763,126.64736 -> wgs84 近似)
ENDPOINTS = [None,
             "https://lz4.overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.osm.jp/api/interpreter"]


def main():
    best = None
    for ep in ENDPOINTS:
        name = ep or "官方默认"
        try:
            ox.settings.requests_timeout = 120
            if ep:
                ox.settings.overpass_url = ep
            G = ox.graph.graph_from_point(CENTER_WGS, dist=1600, network_type="walk")
            n, m = len(G.nodes), len(G.edges)
            print(f"[{name}] 节点 {n} 边 {m}")
            if best is None or n > best[0]:
                best = (n, m, G, name)
        except Exception as e:
            print(f"[{name}] 失败:{str(e)[:80]}")
    if best:
        n, m, G, name = best
        print(f"\n最密:{name} 节点 {n} 边 {m}(缓存图 943/2968)")
        if n > 943 * 1.15:
            fp = os.path.join(ROOT, "experiments", "logs", "osm_harbin_v2.graphml")
            ox.save_graphml(G, fp)
            print(f"显著更密(+{(n / 943 - 1) * 100:.0f}%),已存 {fp}")
        else:
            print("与缓存相当——943 偏稀为道外棚改区真实肌理,非下载截断")


if __name__ == "__main__":
    main()
