"""POI 盲区管线 v1 —— 哈尔滨·道外(零算路配额)

流程(对应设计文档 06/07 与 E7.3):
  1) 五类目 × taxonomy 同义词表,place/v2/search 周边检索(半径 2km,分页)
  2) uid 去重 + 跨关键词去重;单关键词 vs taxonomy 召回对比
  3) 每个设施的步行时长:缓存场 Delaunay 线性插值;场外点用 直线×城市系数/步速 兜底
  4) 体检表:各类目 15min 内设施数 / 最近设施
  5) 盲区:8 扇区盲区图 + 50m 格网盲区格(近似时长 = 直线×k/v,分级:15-18 轻度 / 18-25 中度 / >25 严重)

产出:experiments/results/poi_harbin.json + 体检报告-哈尔滨道外.md
"""
import json
import math
import os
import sys
import time

import numpy as np
from scipy.interpolate import griddata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
K_DET = 1.31          # 哈尔滨实测中位绕行系数(E5)
V_MS = 4.2 / 3.6      # 实测中位步速

TAXONOMY = {
    "医疗": ["医院", "社区卫生服务中心", "诊所"],
    "教育": ["小学"],
    "购物": ["菜市场", "农贸市场", "生鲜超市"],
    "药店": ["药店", "药房"],
    "养老": ["养老院", "老年活动中心", "日间照料中心", "老年公寓", "福利院",
             "养老服务中心", "长者食堂"],   # 2026-08-31 补词:修复养老类 0 命中疑缺口
}


def flat(o, p):
    return math.hypot((p[0] - o[0]) * 111320,
                      (p[1] - o[1]) * 111320 * math.cos(math.radians(o[0])))


def main():
    city = json.load(open(os.path.join(_ROOT, "experiments", "results",
                                       "e10_boundary", "e10x_harbin.json"), encoding="utf-8"))
    center = tuple(city["center"])
    radii = {float(k): v for k, v in city["radii"].items()}
    print(f"社区:哈尔滨·道外 中心 {center[0]:.5f},{center[1]:.5f} | 等时圈射线 {len(radii)}")

    # 缓存场(该中心)
    import sqlite3
    db = os.path.join(_ROOT, "experiments", "logs", "cache.db")
    field = {}
    with sqlite3.connect(db) as c:
        for d_lat, d_lng, dur in c.execute(
                "SELECT d_lat,d_lng,duration_s FROM walk_times WHERE o_lat=? AND o_lng=?",
                (round(center[0], 6), round(center[1], 6))):
            if dur is not None:
                field[(d_lat, d_lng)] = dur
    fpts = np.array([(k[0], k[1]) for k in field])
    fvals = np.array([field[k] for k in field])
    print(f"缓存场:{len(field)} 点(Delaunay 插值用)")

    # ---- POI 检索(taxonomy;带关键词级缓存,二跑零调用)----
    pcache_fp = os.path.join(_ROOT, "experiments", "results", "poi",
                             "poi_search_cache.json")
    pcache = {}
    if os.path.exists(pcache_fp):
        pcache = json.load(open(pcache_fp, encoding="utf-8"))
    api_calls = [0]

    def search(kw, page):
        ck = f"{kw}|{page}|2000"
        if ck in pcache:
            return pcache[ck], True
        r = bc.place_search(kw, location=center, radius=2000, page_size=20,
                            page_num=page, experiment_id="POI_HARBIN")
        if not r.ok:
            return None, False
        api_calls[0] += 1
        pcache[ck] = r.data.get("results") or []
        return pcache[ck], True

    pois = {}                      # uid -> poi
    kw_stats = []
    for cat, kws in TAXONOMY.items():
        single_n = 0
        for kw in kws:
            page = 0
            while page < 3:
                res, okc = search(kw, page)
                if not okc:
                    print(f"  [{kw}] p{page} FAIL")
                    break
                for it in res:
                    uid = it.get("uid") or f"{it['name']}{it['location']['lat']:.5f}"
                    loc = it["location"]
                    p = (loc["lat"], loc["lng"])
                    if uid not in pois:
                        pois[uid] = {"uid": uid, "name": it["name"], "cat": cat,
                                     "kw": kw, "lat": p[0], "lng": p[1],
                                     "address": it.get("address", "") or ""}
                    else:
                        pois[uid]["kw"] += f"+{kw}"      # 跨关键词命中标记
                if kw == kws[0]:
                    single_n += len(res)
                if len(res) < 20:
                    break
                page += 1
                time.sleep(0.4)
            time.sleep(0.4)
        tax_n = sum(1 for v in pois.values() if v["cat"] == cat)
        kw_stats.append({"cat": cat, "single_kw_n": single_n, "taxonomy_n": tax_n,
                         "keywords": kws})
        print(f"  {cat}:单关键词 {single_n} → taxonomy {tax_n}({', '.join(kws)})")

    # ---- 时长估计:Delaunay 场内,兜底场外 ----
    coords = np.array([(v["lat"], v["lng"]) for v in pois.values()])
    t_hat = griddata(fpts, fvals, coords, method="linear")
    for v, th in zip(pois.values(), t_hat):
        s = flat(center, (v["lat"], v["lng"]))
        fb = s * K_DET / V_MS
        if th is None or np.isnan(th):
            v["t_s"] = round(fb)
            v["t_src"] = "fallback"
        else:
            v["t_s"] = round(float(th))
            v["t_src"] = "field"
        v["straight_m"] = round(s)
    n_fb = sum(1 for v in pois.values() if v["t_src"] == "fallback")
    print(f"时长估计:场内插值 {len(pois)-n_fb},兜底 {n_fb}")

    # ---- 体检表 ----
    print("\n===== 15 分钟生活圈体检(中心口径)=====")
    report = {"community": "哈尔滨·道外", "center": list(center), "categories": {},
              "kw_stats": kw_stats, "pois": list(pois.values())}
    for cat in TAXONOMY:
        ps = sorted((v for v in pois.values() if v["cat"] == cat), key=lambda v: v["t_s"])
        in15 = [v for v in ps if v["t_s"] <= TH]
        near = ps[0] if ps else None
        report["categories"][cat] = {
            "n_total": len(ps), "n_in15": len(in15),
            "nearest": {"name": near["name"], "t_s": near["t_s"],
                        "straight_m": near["straight_m"]} if near else None,
            "top3_in15": [{"name": v["name"], "t_s": v["t_s"]} for v in in15[:3]],
        }
        c = report["categories"][cat]
        nn = c["nearest"]
        print(f"  {cat}:共 {c['n_total']} 家 | 15min 内 {c['n_in15']} 家 | "
              f"最近 {nn['name']} {nn['t_s']}s({nn['straight_m']}m)"
              if nn else f"  {cat}:无设施")

    # ---- 扇区盲区图 ----
    def bearing_of(p):
        return math.degrees(math.atan2(p[1] - center[1], p[0] - center[0])) % 360

    sectors = {}
    for cat in TAXONOMY:
        covered = set()
        for v in pois.values():
            if v["cat"] == cat and v["t_s"] <= TH:
                covered.add(int(bearing_of((v["lat"], v["lng"])) // 45) % 8)
        blind = sorted(set(range(8)) - covered)
        sectors[cat] = {"covered": sorted(covered), "blind": blind}
    report["sector_blind"] = sectors
    print("\n===== 扇区盲区(8 扇区,北起顺时针)=====")
    for cat, s in sectors.items():
        print(f"  {cat}:覆盖 {[f'{x*45}°' for x in s['covered']]} | "
              f"盲区 {[f'{x*45}°' for x in s['blind']] or '无'}")

    # ---- 50m 格网盲区格(圈内点,近似时长=直线×k/v)----
    import bisect
    ks = sorted(radii)

    def r_at(brg):
        i = bisect.bisect_right(ks, brg) - 1
        b0, b1 = ks[i % len(ks)], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    from core.coord import dest_at
    cells = []
    for i in range(-24, 25):
        lat0, lng0 = dest_at(center[1], center[0], 0, i * 50)
        for j in range(-24, 25):
            lat, lng = dest_at(lng0, lat0, 90, j * 50)
            d = flat(center, (lat, lng))
            b = math.degrees(math.atan2(lng - center[1], lat - center[0])) % 360
            if d < r_at(b) - 20:            # 圈内(留 20m 边界余量)
                cells.append((lat, lng))
    blind_cells = {}
    for cat in TAXONOMY:
        cps = [(v["lat"], v["lng"]) for v in pois.values() if v["cat"] == cat]
        if not cps:
            blind_cells[cat] = {"n_cells": len(cells), "all_blind": True}
            continue
        lv = []
        for cell in cells:
            tmin = min(flat(cell, p) for p in cps) * K_DET / V_MS
            lv.append(tmin)
        lv = sorted(lv)
        blind_cells[cat] = {
            "n_cells": len(cells),
            "blind_gt15": sum(1 for t in lv if t > 900),
            "mild_15_18": sum(1 for t in lv if 900 < t <= 1080),
            "mid_18_25": sum(1 for t in lv if 1080 < t <= 1500),
            "severe_gt25": sum(1 for t in lv if t > 1500),
        }
    report["grid_blind"] = {"lattice": "50m", "n_inside_cells": len(cells),
                            "by_cat": blind_cells}
    print(f"\n===== 格网盲区(圈内 {len(cells)} 格 @50m)=====")
    for cat, b in blind_cells.items():
        if b.get("all_blind"):
            print(f"  {cat}:全部盲区(无设施)")
        else:
            print(f"  {cat}:盲区 {b['blind_gt15']}/{b['n_cells']} 格"
                  f"(轻度 {b['mild_15_18']} / 中度 {b['mid_18_25']} / 严重 {b['severe_gt25']})")

    json.dump(pcache, open(pcache_fp, "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"POI 检索 API 调用 {api_calls[0]} 次(缓存 {len(pcache)} 键)")
    json.dump(report, open(os.path.join(_ROOT, "experiments", "results", "poi", "poi_harbin.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/poi_harbin.json")


if __name__ == "__main__":
    main()
