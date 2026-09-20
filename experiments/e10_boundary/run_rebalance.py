# -*- coding: utf-8 -*-
"""REBAL · 弦差再平衡:消灭"针状"边界(2026-08-31)

问题:mid 违规插入后,两侧弦差可仍 >200m(义乌 95.6°=486m vs 邻 842/805),
多边形把真实凹口画成一根针——欠采样,不是数据错。
规则:凡 |r_a - r_b| > 150m 的弦,在弦中点方位无条件 bisect(tol25),
迭代 ≤3 轮直到无 Δ>150 弦、弧 <2° 或预算尽。EID=REBAL,全局 ≤600 对。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.paths import RESULTS

TH = 900
EID = "REBAL"
GAP = 150.0
ORDER = ["yiwu", "guilin", "harbin", "chongqing", "zunyi", "changsha", "luoyang",
         "xian", "shanghai", "wuhan", "guangzhou", "B", "kunshan", "A", "chengdu"]
FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
GLOBAL_CAP = 1500


def used_all():
    import sqlite3
    with sqlite3.connect(os.path.join(RESULTS, "..", "logs", "calls.db")) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE "
                         "experiment_id LIKE 'REB%'").fetchone()[0]


def run(slug, idx):
    sub, fn, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
    fp = os.path.join(RESULTS, sub, fn)
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d[rk].items()}
    eid = f"REB{idx}"                       # v2:每城独立 EID,杜绝跨城截断
    R = CityRunner(eid, center, cap=120)
    label = d.get("city", slug)

    def flagged():
        ks = sorted(radii)
        out = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            if abs(radii[a % 360] - radii[b % 360]) > GAP and (b - a) > 2.0:
                out.append(((a + b) / 2) % 360)
        return out

    total_ins = 0
    for rd in range(4):
        mids = flagged()
        mids = [m for m in mids
                if not any(abs(m - b) < 0.6 or abs(m - b - 360) < 0.6 for b in radii)]
        if not mids:
            break
        if R.left() < 10:
            print(f"[{label}] 本城预算触顶,剩 {len(mids)} 弦未平衡(如实)")
            break
        spend0 = R.used()
        got = R.bisect(mids, tol=25.0)
        spend = R.used() - spend0
        # v2 关键守卫:零消耗批次 = 全零探针 = 全默认 800m,整批丢弃
        if spend == 0 and got:
            print(f"[{label}] 第{rd+1}轮:零探针批次 {len(got)} 条,丢弃不写盘")
            break
        bad = [b for b, v in got.items() if abs(v - 800.0) < 0.05 and spend == 0]
        for b in bad:
            got.pop(b)
        radii.update(got)
        total_ins += len(got)
        print(f"[{label}] 第{rd+1}轮:平衡 {len(got)} 弦(+{spend} 对,剩 "
              f"{len(flagged())} 条 Δ>{GAP:.0f}m)")

    d[rk] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    if rk != "radii":
        d["radii"] = d[rk]
    d["rays"] = len(radii)
    d.setdefault("rebal", {}).update({"inserted": total_ins,
                                      "pairs": R.used(),
                                      "left_gap": len(flagged())})
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{label}] 完成:+{total_ins} 向,共 {len(radii)} 向,剩针 {len(flagged())}")


def main():
    only = set(sys.argv[1:])
    for idx, slug in enumerate(ORDER):
        if only and slug not in only:
            continue
        if used_all() >= GLOBAL_CAP:
            print("全局预算触顶,停止")
            break
        try:
            run(slug, idx)
        except Exception as e:
            print(f"[{slug}] 失败:{str(e)[:120]}")
    print(f"\nREBAL 家族总耗 {used_all()} 对")


if __name__ == "__main__":
    main()
