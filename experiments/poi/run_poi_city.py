# -*- coding: utf-8 -*-
"""POI 体检 · 通用版(C 项:第二/多社区泛化,2026-09-01)

用法:.venv/Scripts/python.exe experiments/poi/run_poi_city.py <slug>
读取 e10x_{slug}.json(center/radii/rho.median),五类 taxonomy 检索(关键词缓存键
含中心坐标——修复跨城串缓存),Delaunay 场插值+兜底,扇区/50m 格网盲区,加权评分。
产出:results/poi/poi_{slug}.json。EID=POI_{slug}。
"""
import json
import math
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
from scipy.interpolate import griddata

from core import baidu_client as bc
from core import cache as wcache
from core.coord import dest_at
from experiments.paths import RESULTS

TH = 900
K_DET_FALLBACK = 1.4      # 无该城 ρ 时的兜底
V_MS = 4.2 / 3.6
WEIGHTS = {"医疗": 0.25, "教育": 0.20, "购物": 0.20, "药店": 0.15, "养老": 0.20}
TAXONOMY = {
    "医疗": ["医院", "社区卫生服务中心", "诊所"],
    "教育": ["小学"],
    "购物": ["菜市场", "农贸市场", "生鲜超市"],
    "药店": ["药店", "药房"],
    "养老": ["养老院", "老年活动中心", "日间照料中心", "老年公寓", "福利院",
             "养老服务中心", "长者食堂"],
}


def load_field(center):
    con = sqlite3.connect(os.path.join(RESULTS, "..", "logs", "cache.db"))
    out = {}
    for dlat, dlng, dur in con.execute(
            "SELECT d_lat,d_lng,duration_s FROM walk_times "
            "WHERE o_lat BETWEEN ?-1e-5 AND ?+1e-5 AND o_lng BETWEEN ?-1e-5 AND ?+1e-5",
            (center[0], center[0], center[1], center[1])):
        if dur is not None:
            out[(round(dlat, 6), round(dlng, 6))] = dur
    return out


def main(slug):
    d = json.load(open(os.path.join(RESULTS, "e10_boundary", f"e10x_{slug}.json"),
                       encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    k_det = ((d.get("rho") or {}).get("median") or K_DET_FALLBACK)
    ks = sorted(radii)
    label = d["city"]

    def r_at(brg):
        i = 0
        for j in range(len(ks)):
            if ks[j] <= brg:
                i = j
        b0, b1 = ks[i], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    field = load_field(center)
    fpts = np.array(list(field.keys()))
    fvals = np.array(list(field.values()))
    print(f"== {label} 体检 | 场 {len(field)} 点 | ρ={k_det}")

    # POI 检索(键含中心,防跨城串缓存)
    pfp = os.path.join(RESULTS, "poi", "poi_search_cache.json")
    pcache = json.load(open(pfp, encoding="utf-8")) if os.path.exists(pfp) else []
    pcache = {k: v for k, v in (pcache.items() if isinstance(pcache, dict) else [])}
    api_calls = [0]

    def search(kw, page):
        ck = f"{kw}|{page}|{center[0]:.4f},{center[1]:.4f}|2000"
        if ck in pcache:
            return pcache[ck]
        r = bc.place_search(kw, location=center, radius=2000, page_size=20,
                            page_num=page, experiment_id=f"POI_{slug}")
        if not r.ok:
            return None
        api_calls[0] += 1
        pcache[ck] = r.data.get("results") or []
        return pcache[ck]

    pois = {}
    for cat, kws in TAXONOMY.items():
        for kw in kws:
            page = 0
            while page < 3:
                res = search(kw, page)
                if res is None:
                    break
                for it in res:
                    uid = it.get("uid") or f"{it['name']}{it['location']['lat']:.5f}"
                    loc = it["location"]
                    if uid not in pois:
                        pois[uid] = {"uid": uid, "name": it["name"], "cat": cat,
                                     "kw": kw, "lat": loc["lat"], "lng": loc["lng"]}
                    else:
                        pois[uid]["kw"] += f"+{kw}"
                if len(res) < 20:
                    break
                page += 1
                time.sleep(0.3)
            time.sleep(0.3)
    json.dump(pcache, open(pfp, "w", encoding="utf-8"), ensure_ascii=False)

    # 时长估计
    coords = np.array([(v["lat"], v["lng"]) for v in pois.values()])
    t_hat = griddata(fpts, fvals, coords, method="linear") if len(pois) >= 4 else [None] * len(pois)
    for v, th in zip(pois.values(), t_hat):
        s = math.hypot((v["lat"] - center[0]) * 111320,
                       (v["lng"] - center[1]) * 111320 * math.cos(math.radians(center[0])))
        fb = s * k_det / V_MS
        if th is None or np.isnan(th):
            v["t_s"], v["t_src"] = round(fb), "fallback"
        else:
            v["t_s"], v["t_src"] = round(th), "field"
        v["straight_m"] = round(s)

    cats = {}
    for cat in WEIGHTS:
        sub = [v for v in pois.values() if v["cat"] == cat]
        in15 = sorted([v for v in sub if v["t_s"] <= TH], key=lambda v: v["t_s"])
        cats[cat] = {"n_total": len(sub), "n_in15": len(in15),
                     "nearest": in15[0] if in15 else None}

    # 扇区盲区 + 50m 格网盲区
    sector = {}
    for cat in WEIGHTS:
        blind = []
        for i in range(8):
            b0, b1 = i * 45, (i + 1) * 45
            cov = any(v["t_s"] <= TH and
                      b0 <= (math.degrees(math.atan2((v["lng"] - center[1]) * 111320 *
                                                      math.cos(math.radians(center[0])),
                                                      (v["lat"] - center[0]) * 111320)) % 360) < b1
                      for v in pois.values() if v["cat"] == cat)
            if not cov:
                blind.append(f"{b0}°")
        sector[cat] = {"covered": 8 - len(blind), "blind": blind}

    cells = []
    for i in range(-24, 25):
        lat0, lng0 = dest_at(center[1], center[0], 0, i * 50)
        for j in range(-24, 25):
            lat, lng = dest_at(lng0, lat0, 90, j * 50)
            dd = math.hypot((lat - center[0]) * 111320,
                            (lng - center[1]) * 111320 * math.cos(math.radians(center[0])))
            bb = math.degrees(math.atan2((lng - center[1]) * 111320 *
                                         math.cos(math.radians(center[0])),
                                         (lat - center[0]) * 111320)) % 360
            if dd < r_at(bb) - 20:
                cells.append((lat, lng))
    grid_blind = {}
    for cat in WEIGHTS:
        sub = [v for v in pois.values() if v["cat"] == cat]
        n_blind = 0
        for (lat, lng) in cells:
            tmin = min((math.hypot((lat - v["lat"]) * 111320,
                                   (lng - v["lng"]) * 111320 *
                                   math.cos(math.radians(lat)))
                        for v in sub), default=1e9) * k_det / V_MS
            if tmin > TH:
                n_blind += 1
        grid_blind[cat] = {"n_cells": len(cells), "blind_gt15": n_blind}

    score = sum(WEIGHTS[c] * (len(cells) - grid_blind[c]["blind_gt15"]) / max(1, len(cells)) * 100
                for c in WEIGHTS)
    print("\n== 体检表 ==")
    for cat in WEIGHTS:
        c = cats[cat]
        near = c["nearest"]
        print(f"  {cat}: {c['n_in15']}/{c['n_total']} 进圈 | 扇区盲 {len(sector[cat]['blind'])}/8 "
              f"| 格盲 {grid_blind[cat]['blind_gt15']}/{len(cells)}"
              + (f" | 最近 {near['name']} {near['t_s']}s" if near else ""))
    print(f"  综合评分 {score:.1f}/100 | POI API {api_calls[0]} 次")

    json.dump({"community": label, "center": list(center), "k_det": k_det,
               "categories": cats, "sector_blind": sector,
               "grid_blind": {"n_inside_cells": len(cells), "by_cat": grid_blind},
               "score": round(score, 1),
               "pois": list(pois.values())},
              open(os.path.join(RESULTS, "poi", f"poi_{slug}.json"), "w",
                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已写 results/poi/poi_{slug}.json")


if __name__ == "__main__":
    main(sys.argv[1])
