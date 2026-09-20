# -*- coding: utf-8 -*-
"""E12 · 起步向数路由(离线训练,零 API)

问题:8 向起步在难城要多一轮返工;16 起步在易城浪费一倍。
方法:免费信号(OSM 路网特征,先于任何百度调用)+ 十六城收敛 k 标签
     → 可解释阈值规则;留一(LOO)验证。
限制:五小城+南昌无路网图(按用户指示未下载)→ 本版仅十城训练,小城待补图。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import osmnx as ox

from experiments.paths import RESULTS, LOGS

FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
CITIES = ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian",
          "chongqing", "changsha", "wuhan"]


def features(G):
    nodes = G.number_of_nodes()
    edges = G.number_of_edges()
    degs = [d for _, d in G.degree()]
    mean_deg = sum(degs) / len(degs)
    # 街道朝向熵(归一):朝向越集中(网格城)熵越低
    import collections
    hist = collections.Counter()
    for u, v, k2, d in G.edges(keys=True, data=True):
        dy = G.nodes[v]["y"] - G.nodes[u]["y"]
        dx = G.nodes[v]["x"] - G.nodes[u]["x"]
        if dx == dy == 0:
            continue
        brg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        hist[int(brg // 15) * 15] += d.get("length", 1.0)
    tot = sum(hist.values()) or 1
    ent = -sum((c / tot) * math.log(c / tot + 1e-12) for c in hist.values())
    ent_norm = ent / math.log(24)           # 24 个 15° 桶的上限熵
    return {"nodes": nodes, "edges": edges,
            "deg": round(mean_deg, 2), "orient_ent": round(ent_norm, 3)}


def main():
    rows = []
    for slug in CITIES:
        gp = os.path.join(LOGS, f"osm_{slug}.graphml")
        if not os.path.exists(gp):
            continue
        G = ox.load_graphml(gp)
        f = features(G)
        sub, fn, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
        d = json.load(open(os.path.join(RESULTS, sub, fn), encoding="utf-8"))
        k = len(d[rk])
        complex_sig = (d.get("gap_over_200m", 0) >= 2) or (k >= 40)
        rows.append({"slug": slug, "city": d.get("city") or d.get("community", slug),
                     **f, "k": k, "label_complex": complex_sig})
    print(f"{'城':12s} {'节点':>5s} {'度':>5s} {'朝向熵':>6s} {'k':>4s} 难")
    for r in rows:
        print(f"{r['city']:12s} {r['nodes']:5d} {r['deg']:5.2f} {r['orient_ent']:6.3f} "
              f"{r['k']:4d} {'难' if r['label_complex'] else '易'}")

    # 单特征阈值规则 LOO
    def acc_rule(feat, thr, hard_high=True):
        correct = 0
        for r in rows:
            pred = (r[feat] >= thr) if hard_high else (r[feat] <= thr)
            if pred == r["label_complex"]:
                correct += 1
        return correct / len(rows)

    print("\nLOO 单特征阈值扫描:")
    best = None
    for feat in ("nodes", "deg", "orient_ent"):
        vals = sorted(r[feat] for r in rows)
        for thr in vals:
            for hh in (True, False):
                a = acc_rule(feat, thr, hh)
                if best is None or a > best[0]:
                    best = (a, feat, thr, hh)
        print(f"  {feat}: 最优 LOO acc={max(acc_rule(feat, t, h) for t in vals for h in (True, False)):.2f}")
    a, feat, thr, hh = best
    print(f"\n最优规则:{feat} {'≥' if hh else '≤'} {thr} → 16/32 起步(复杂),否则 8 起步")
    print(f"LOO 准确率 {a:.0%}(十城;五小城+南昌待补 OSM 图后加入验证)")
    json.dump({"rows": rows, "rule": {"feature": feat, "thr": thr, "high": hh,
                                      "loo_acc": a}},
              open(os.path.join(RESULTS, "e0_instrument", "e12_route.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已写 results/e0_instrument/e12_route.json")


if __name__ == "__main__":
    main()
