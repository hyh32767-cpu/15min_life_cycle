# -*- coding: utf-8 -*-
"""S5B · 小角度弦验证:十六城批量应用(2026-09-01,配额恢复)

规则(南昌实证 +3.3pt IoU/80对):候选弦 = arc≤22.5° 且(Δr>80m 或 arc≤11.25°);
在边中点 C_mid(两端点线性中点)实测:超时=凹;1.06·C_mid 可达=凸 → 弦中点方位插向(tol25)。
工程守卫(v2 教训):每城独立 EID;零消耗批次整批丢弃;bisect 返回 None 不写盘。
对象:十五城 + 南昌(第 2 轮续跑)。产出:更新 e10x_*.json radii + s5b 字段。
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.paths import RESULTS

TH = 900
FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
ORDER = ["harbin", "chongqing", "zunyi", "guilin", "changsha", "luoyang", "xian",
         "shanghai", "wuhan", "guangzhou", "B", "kunshan", "A", "chengdu", "yiwu",
         "nanchang"]
CAP_PER_CITY = 400
GLOBAL_CAP = 1500  # 边探针多轮累积在缓存,续跑只付二分


def used_all():
    import sqlite3
    with sqlite3.connect(os.path.join(RESULTS, "..", "logs", "calls.db")) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE "
                         "experiment_id LIKE 'S5B%'").fetchone()[0]


def run(slug, idx):
    sub, fn, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
    fp = os.path.join(RESULTS, sub, fn)
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d[rk].items()}
    R = CityRunner(f"S5B{idx:02d}", center, cap=CAP_PER_CITY)
    label = d.get("city") or d.get("community") or slug
    kcos = math.cos(math.radians(center[0]))
    total_ins = 0

    for rd in range(3):
        if R.left() < 8:
            print(f"[{label}] 本城预算触顶,停止(如实)")
            break
        ks = sorted(radii)
        ins = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            arc = (b - a) % 360 or 360
            dz = abs(radii[a % 360] - radii[b % 360])
            if not (arc <= 22.5 and (dz > 80 or arc <= 11.25)):
                continue
            mb = ((a + b) / 2) % 360
            if any(abs(mb - x) < 0.6 or abs(mb - x - 360) < 0.6 for x in radii):
                continue
            pa = R.endpoint(a % 360, radii[a % 360])
            pb = R.endpoint(b % 360, radii[b % 360])
            cm = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            dd = math.hypot((cm[0] - center[0]) * 111320,
                            (cm[1] - center[1]) * 111320 * kcos)
            t1 = R.t_of(cm) if R.t_of(cm) is not None else None
            R.measure([cm])
            t1 = R.t_of(cm)
            cm2 = R.endpoint(mb, dd * 1.06)
            R.measure([cm2])
            t2 = R.t_of(cm2)
            why = ("凹" if (t1 is not None and t1 > TH)
                   else ("凸" if (t2 is not None and t2 <= TH) else ""))
            if why:
                ins.append((round(mb, 2), why))
        if not ins:
            print(f"[{label}] S5b 一致 ✓(第{rd+1}轮)")
            break
        ok_ins = []
        for mb, why in ins:
            if R.left() < 15:
                print(f"[{label}] 插向前预算不足,停止(候选剩余不写盘)")
                break
            spend_b = R.used()
            v = R.bisect([mb], tol=25.0).get(mb)
            if v is None or R.used() == spend_b or abs(v - 800.0) < 0.05:
                continue                      # 零探针默认值:当场丢弃,绝不入 radii
            radii[mb] = v
            ok_ins.append((mb, why, round(v)))
        if not ok_ins:
            print(f"[{label}] 第{rd+1}轮:有效插向 0(候选 {len(ins)},零探针全弃)")
            break
        total_ins += len(ok_ins)
        print(f"[{label}] 第{rd+1}轮:{ok_ins} → k={len(radii)}")

    d[rk] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    if rk != "radii":
        d["radii"] = d[rk]
    d["rays"] = len(radii)
    d.setdefault("s5b", {}).update({"inserted": total_ins, "pairs": R.used()})
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{label}] 完成:+{total_ins} 向,k={len(radii)},耗 {R.used()} 对")


def main():
    only = set(sys.argv[1:])
    for idx, slug in enumerate(ORDER):
        if only and slug not in only:
            continue
        if used_all() >= GLOBAL_CAP:
            print("全局预算触顶,停止")
            break
        for attempt in range(3):
            try:
                run(slug, idx)
                break
            except Exception as e:
                msg = str(e)
                if ('network' in msg or 'ssl' in msg.lower() or 'SSL' in msg)                    and attempt < 2:
                    print(f"[{slug}] 网络抖动,90s 后重试({msg[:60]})")
                    import time as _t
                    _t.sleep(90)
                    continue
                print(f"[{slug}] 失败:{msg[:120]}")
                break
    print(f"\nS5B 家族总耗 {used_all()} 对")


if __name__ == "__main__":
    main()
