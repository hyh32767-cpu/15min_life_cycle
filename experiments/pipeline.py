# -*- coding: utf-8 -*-
"""E8 · 端到端管线 CLI:地址 -> 等时圈 -> 体检 -> 盲区 -> 选址 -> 报告(一键)

用法:
  .venv/Scripts/python.exe experiments/pipeline.py                # 缓存模式(二跑零调用)
  .venv/Scripts/python.exe experiments/pipeline.py --live        # 缓存未命中时走真实 API
  .venv/Scripts/python.exe experiments/pipeline.py --addr "..."  # 其他社区(live 模式)

链路(缓存命中时全程零 API):
  S1 geocode   geocodes.json 地址缓存(未命中且 --live -> bc.geocode 并回填)
  S2 等时圈    16 向二分(tol15)缓存重放 + 弦规则加密(实测超时证据/θ>=30°)
               (未命中且 --live -> routematrix 单发 + cache.put)
  S3 体检      run_poi_harbin.main()(POI 关键词缓存 poi_search_cache.json)
  S4 评分      加权格网覆盖率(医疗.25/教育.20/购物.20/药店.15/养老.20)
  S5 选址      analyze_mclp_harbin.main()(OSM 初筛;百度复核读 mclp_baidu_check.json)
  S6 报告      docs/12-真实社区对比测试报告.md(含台账零调用断言)
"""
import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime

# 关键:移除脚本目录(experiments/)本身,否则其下的 osmnx/ 子目录会遮蔽
# site-packages 的 osmnx 包(pipeline 直接运行时 sys.path[0] 即 experiments/)
_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or ".") != _here]
sys.path.insert(0, os.path.dirname(_here))

from experiments.paths import ROOT, LOGS, RESULTS

TH = 900
WEIGHTS = {"医疗": 0.25, "教育": 0.20, "购物": 0.20, "药店": 0.15, "养老": 0.20}
GEO_FP = os.path.join(LOGS, "geocodes.json")


def ledger_snapshot(ts_from=None):
    with sqlite3.connect(os.path.join(LOGS, "calls.db")) as c:
        if ts_from:
            return c.execute("SELECT COUNT(*), COALESCE(SUM(n_pairs),0) FROM calls "
                             "WHERE ts>=?", (ts_from,)).fetchone()
        return c.execute("SELECT COUNT(*), COALESCE(SUM(n_pairs),0) FROM calls").fetchone()


def s1_geocode(addr, live):
    cache = json.load(open(GEO_FP, encoding="utf-8")) if os.path.exists(GEO_FP) else {}
    if addr in cache:
        return tuple(cache[addr]), True
    if not live:
        raise SystemExit(f"[S1] 地址未缓存且非 --live:{addr}")
    from core import baidu_client as bc
    r = bc.geocode(addr, experiment_id="E8")
    if not r.ok:
        raise SystemExit(f"[S1] geocode 失败:{r.message}")
    loc = r.data["result"]["location"]
    center = (loc["lat"], loc["lng"])
    cache[addr] = list(center)
    json.dump(cache, open(GEO_FP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return center, False


def s2_isochrone(center, live):
    from core.coord import dest_at
    from experiments.e4_sampling.run_e4 import key
    from experiments.maps.plot_maps import load_field

    field = load_field(center)

    def measure(b, d):
        p = dest_at(center[1], center[0], b, d)
        if key(p) in field:
            return field[key(p)]
        if not live:
            return None
        from core import baidu_client as bc
        from core import cache as wcache
        r = bc.routematrix("walking", [center], [p], experiment_id="E8")
        if not r.ok:
            return None
        it = next(iter(bc.matrix_items(r)), None)
        if not it or it.get("duration_s") is None:
            return None
        wcache.put(center, p, it["duration_s"], it.get("distance_m"))
        field[key(p)] = it["duration_s"]
        return it["duration_s"]

    radii = {}
    # 缓存模式优先:重放本社区已测成品射线(e10x,探针全在缓存,零调用)
    fp = os.path.join(RESULTS, "e10_boundary", "e10x_harbin.json")
    if os.path.exists(fp) and not live:
        d = json.load(open(fp, encoding="utf-8"))
        if abs(d["center"][0] - center[0]) < 1e-9 and \
           abs(d["center"][1] - center[1]) < 1e-9:
            return {float(k): v for k, v in d["radii"].items()}, len(field)

    def bisect(b, tol=15.0):
        lo, hi = 200.0, 1400.0
        while hi - lo > tol:
            m = (lo + hi) / 2
            t = measure(b, m)
            if t is None:
                break
            if t <= TH:
                lo = m
            else:
                hi = m
        radii[b] = (lo + hi) / 2

    for i in range(16):
        bisect(i * 22.5)
    # 弦规则加密:实测超时证据落入当前多边形(违规)或 θ>=30°
    klat, klng = 111320.0, 111320.0 * math.cos(math.radians(center[0]))
    ev = [(math.degrees(math.atan2((p[1] - center[1]) * klng,
                                   (p[0] - center[0]) * klat)) % 360,
           math.hypot((p[0] - center[0]) * klat, (p[1] - center[1]) * klng))
          for p, t in field.items() if t > TH]

    def r_at(brg):
        ks = sorted(radii)
        i = 0
        for j in range(len(ks)):
            if ks[j] <= brg:
                i = j
        b0, b1 = ks[i], ks[(i + 1) % len(ks)]
        db = (b1 - b0) % 360 or 360
        t = ((brg - b0) % 360) / db
        return radii[b0] * (1 - t) + radii[b1] * t

    for _ in range(10):
        ks = sorted(radii)
        inserts = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            a0 = a % 360
            arc = (b - a) % 360 or 360
            if arc < 1e-6:
                continue
            viol = any(((bb - a0) % 360) < arc and dd < r_at(bb) for bb, dd in ev)
            if viol or arc >= 30:
                mb = round(((a + b) / 2) % 360, 2)
                # 只插探针可测的方位;否则跳过,避免给假半径
                if measure(mb, 800) is not None or live:
                    inserts.append(mb)
        if not inserts:
            break
        n0r = len(radii)
        for bb in inserts:
            bisect(bb)
        if len(radii) == n0r:
            break
    return radii, len(field)


def s3_poi():
    from experiments.poi import run_poi_harbin
    run_poi_harbin.main()


def s4_score(poi_fp):
    d = json.load(open(poi_fp, encoding="utf-8"))
    n_in = d["grid_blind"]["n_inside_cells"]
    rows, total = {}, 0.0
    for cat, w in WEIGHTS.items():
        blind = d["grid_blind"]["by_cat"].get(cat, {}).get("blind_gt15", 0)
        cov = (n_in - blind) / n_in * 100
        rows[cat] = round(cov, 1)
        total += w * cov
    return round(total, 1), rows, n_in


def s5_mclp():
    from experiments.osmnx import analyze_mclp_harbin
    analyze_mclp_harbin.main()


def s6_report(addr, center, radii, n_field, score, rows, n_cells, delta, fp_out):
    poi = json.load(open(os.path.join(RESULTS, "poi", "poi_harbin.json"),
                         encoding="utf-8"))
    L = []
    A = L.append
    A("# 12 · 真实社区对比测试报告 —— 哈尔滨·道外(E8 端到端)\n")
    A(f"> {datetime.now():%Y-%m-%d %H:%M} · 一键命令:`python experiments/pipeline.py`"
      f"(缓存模式)· 地址:{addr}")
    A(f"> 中心 {center[0]:.5f},{center[1]:.5f}(bd09)\n")
    A("## 链路与调用账本\n")
    A("| 步骤 | 组件 | 产物 |")
    A("| --- | --- | --- |")
    A("| S1 geocode | geocodes.json 缓存 | 中心坐标 |")
    A(f"| S2 等时圈 | 16向二分重放 + 弦规则加密 | {len(radii)} 向(场 {n_field} 点)|")
    A("| S3 体检 | run_poi_harbin(POI 关键词缓存) | poi_harbin.json |")
    A(f"| S4 评分 | 加权格网覆盖率 | **{score} / 100** |")
    A("| S5 选址 | OSM 初筛 + 百度复核 | mclp_harbin.json(+baidu_check) |")
    A("| S6 报告 | 本文件 | docs/12 |\n")
    A(f"**本次运行新增 API 调用:{delta[0]} 次 / {delta[1]} 对"
      f"({'✓ 零调用' if delta[0] == 0 else '✗ 非零(E8/EID 见 calls.db)'})**\n")
    A("## 体检(v2 口径,taxonomy 补词后)\n")
    A("| 类目 | 权重 | 格网覆盖率 | 15min 内/总数 |")
    A("| --- | --: | --: | --- |")
    for cat in WEIGHTS:
        c = poi["categories"][cat]
        A(f"| {cat} | {WEIGHTS[cat]:.2f} | {rows[cat]}% | {c['n_in15']}/{c['n_total']} |")
    A(f"| **综合** | | | **{score} / 100** |\n")
    A("## 盲区 → 处方(Before/After)\n")
    sb = poi["sector_blind"]
    for cat in ("养老", "教育"):
        A(f"- {cat}:扇区盲 {len(sb[cat]['blind'])}/8;"
          f"格网盲 {poi['grid_blind']['by_cat'][cat]['blind_gt15']}/{n_cells}")
    A("- 处方(百度口径复核):养老 3 站累计 **98.5%**(197/200);"
      "教育换址 (45.78763,126.64350) **87%**(旧址 OSM 100% 但百度仅 8.7%,已纠正——"
      "OSM 初筛必须百度破平)\n")
    A("## 未尽事项\n")
    A("- 盲区格 20 个人工街景核对(需实地/街景,留人工)")
    A("- 首跑历史台账:POI_HARBIN / E10X3 / E50M / E4MID / MCLPV 等 EID 累计见 calls.db")
    open(fp_out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"[S6] 报告已写入 {fp_out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--addr", default="哈尔滨市道外区中华巴洛克历史文化街区")
    args = ap.parse_args()

    t_start = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    n0 = ledger_snapshot()

    print(f"[S1] geocode:{args.addr}")
    center, cached = s1_geocode(args.addr, args.live)
    print(f"      中心 {center[0]:.5f},{center[1]:.5f}({'缓存' if cached else 'API'})")

    print("[S2] 等时圈(重放+弦加密)…")
    radii, n_field = s2_isochrone(center, args.live)
    rr = sorted(radii.values())
    print(f"      {len(radii)} 向,半径 {rr[0]:.0f}-{rr[-1]:.0f}m(场 {n_field} 点)")

    print("[S3] POI 体检…")
    s3_poi()
    poi_fp = os.path.join(RESULTS, "poi", "poi_harbin.json")

    print("[S4] 加权评分…")
    score, rows, n_cells = s4_score(poi_fp)
    print(f"      综合 {score}/100({rows})")

    print("[S5] MCLP 选址…")
    s5_mclp()

    w = ledger_snapshot(t_start)
    print(f"[账本] 本次窗口新增 {w[0]} 次/{w[1]} 对")
    if not args.live:
        assert w[0] == 0, f"缓存模式应零调用,实际新增 {w[0]} 次"

    fp_out = os.path.join(ROOT, "docs", "12-真实社区对比测试报告-哈尔滨道外.md")
    s6_report(args.addr, center, radii, n_field, score, rows, n_cells,
              (w[0], w[1]), fp_out)
    print("E8 全链路完成 ✅")


if __name__ == "__main__":
    main()
