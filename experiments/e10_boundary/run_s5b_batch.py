# -*- coding: utf-8 -*-
"""S5B · 小角度弦验证(批量版 v3,2026-09-01)

v3 要点(用户指出逐点单发太慢):
  - 候选边探针(C_mid 与 1.06·C_mid)按 50 对/请求批量打包
  - 二分改为"全向并行分波":每波把所有活跃向的当前中点一次批量测,~6 波收敛
  - 缓存幂等;零探针波整波弃;budget 不足当场停(不写默认值)
规则同 v2:arc≤22.5° 且(Δr>80 或 arc≤11.25°);C_mid 超时=凹;1.06 可达=凸。
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache as wcache
from core.coord import dest_at
from experiments.paths import RESULTS

TH = 900
FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
ORDER = ["harbin", "chongqing", "zunyi", "guilin", "changsha", "luoyang", "xian",
         "shanghai", "wuhan", "guangzhou", "B", "kunshan", "A", "chengdu", "yiwu",
         "nanchang"]
CAP_PER_CITY = 500
GLOBAL_CAP = 1600
DB = os.path.join(RESULTS, "..", "logs", "calls.db")


def spent(eid):
    import sqlite3
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE "
                         "experiment_id=?", (eid,)).fetchone()[0]


def batch_measure(eid, center, pts):
    """缓存优先,未命中按 ≤50 对/请求批量;返回与 pts 对齐的时长列表(None=缺)。"""
    out = []
    for i in range(0, len(pts), 50):
        chunk = pts[i:i + 50]
        vals = []
        todo, tidx = [], []
        for k2, p in enumerate(chunk):
            row = wcache.get(center, p)
            if row and row[0] is not None:
                vals.append(row[0])
            else:
                vals.append(None)
                todo.append(p)
                tidx.append(k2)
        if todo:
            if spent(eid) + len(todo) > CAP_PER_CITY:
                return None                      # 预算不足:整批放弃(不写默认)
            for attempt in range(4):
                r = bc.routematrix("walking", [center], todo, experiment_id=eid)
                if r.ok:
                    break
                if r.status in (401, 302) and attempt < 3:
                    time.sleep([15, 30, 60][attempt])
                    continue
                if "network" in str(r.message) or "SSL" in str(r.message):
                    time.sleep(20)
                    continue
                raise RuntimeError(f"matrix {r.status} {r.message}")
            for p, it in zip(todo, bc.matrix_items(r)):
                if it.get("duration_s") is not None:
                    wcache.put(center, p, it["duration_s"], it.get("distance_m"))
            for k2, p in zip(tidx, todo):
                row = wcache.get(center, p)
                vals[k2] = row[0] if row else None
        out += vals
    return out


def wave_bisect(eid, center, mids, tol=25.0):
    """全向并行二分:每波批量测所有活跃向中点。"""
    lo = {b: 200.0 for b in mids}
    hi = {b: 1400.0 for b in mids}
    done = {}
    for wave in range(12):
        cur = {b: (lo[b] + hi[b]) / 2 for b in mids}
        pts = [dest_at(center[1], center[0], b, cur[b]) for b in mids]
        ts = batch_measure(eid, center, pts)
        if ts is None:
            return done, False                  # 预算断:已完成的保留,其余如实弃
        nxt = []
        for b, t in zip(mids, ts):
            if t is None:
                continue                          # 该向数据缺:弃
            if t <= TH:
                lo[b] = cur[b]
            else:
                hi[b] = cur[b]
            if hi[b] - lo[b] > tol:
                nxt.append(b)
            else:
                done[b] = (lo[b] + hi[b]) / 2
        mids = nxt
        if not mids:
            return done, True
    return done, True


def run(slug, idx):
    sub, fn, rk = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json", "radii"))
    fp = os.path.join(RESULTS, sub, fn)
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d[rk].items()}
    eid = f"S5T{idx:02d}"
    label = d.get("city") or d.get("community") or slug
    kcos = math.cos(math.radians(center[0]))
    total_ins = 0

    for rd in range(3):
        ks = sorted(radii)
        cands = []                                # (mb, cm, cm2)
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            arc = (b - a) % 360 or 360
            dz = abs(radii[a % 360] - radii[b % 360])
            if not (arc <= 22.5 and (dz > 80 or arc <= 11.25)):
                continue
            mb = ((a + b) / 2) % 360
            if any(abs(mb - x) < 0.6 or abs(mb - x - 360) < 0.6 for x in radii):
                continue
            pa = dest_at(center[1], center[0], a % 360, radii[a % 360])
            pb = dest_at(center[1], center[0], b % 360, radii[b % 360])
            cm = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            dd = math.hypot((cm[0] - center[0]) * 111320,
                            (cm[1] - center[1]) * 111320 * kcos)
            cm2 = dest_at(center[1], center[0], mb, dd * 1.06)
            cands.append((round(mb, 2), cm, cm2))
        if not cands:
            print(f"[{label}] S5b 一致 ✓(第{rd+1}轮,候选 0)", flush=True)
            break
        pts = []
        for mb, cm, cm2 in cands:
            pts += [cm, cm2]
        ts = batch_measure(eid, center, pts)
        if ts is None:
            print(f"[{label}] 预算不足,边探针未完(如实停)", flush=True)
            break
        ins = []
        for i2, (mb, cm, cm2) in enumerate(cands):
            t1, t2 = ts[i2 * 2], ts[i2 * 2 + 1]
            why = ("凹" if (t1 is not None and t1 > TH)
                   else ("凸" if (t2 is not None and t2 <= TH) else ""))
            if why:
                ins.append((mb, why))
        if not ins:
            print(f"[{label}] 第{rd+1}轮:候选 {len(cands)} 全部通过 ✓", flush=True)
            break
        got, ok = wave_bisect(eid, center, [m for m, _ in ins])
        ok_ins = [(m, w, round(got[m])) for m, w in ins if m in got
                  and abs(got[m] - 800.0) > 0.05]
        if not ok_ins:
            print(f"[{label}] 第{rd+1}轮:插向未落地({len(ins)} 候选,预算/数据缺)",
                  flush=True)
            break
        for m, _, v in ok_ins:
            radii[m] = v
        total_ins += len(ok_ins)
        print(f"[{label}] 第{rd+1}轮:{ok_ins} → k={len(radii)}", flush=True)

    d[rk] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    if rk != "radii":
        d["radii"] = d[rk]
    d["rays"] = len(radii)
    d.setdefault("s5b", {}).update({"inserted": d.get("s5b", {}).get("inserted", 0)
                                    + total_ins, "pairs": spent(eid)})
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{label}] 完成:+{total_ins} 向,k={len(radii)},城内累计 {spent(eid)} 对",
          flush=True)


def main():
    only = set(sys.argv[1:])
    tot0 = 0
    import sqlite3
    for idx, slug in enumerate(ORDER):
        if only and slug not in only:
            continue
        with sqlite3.connect(DB) as c:
            g = c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE "
                          "experiment_id LIKE 'S5T%'").fetchone()[0]
        if g >= GLOBAL_CAP:
            print("全局预算触顶,停止", flush=True)
            break
        for attempt in range(3):
            try:
                run(slug, idx)
                break
            except Exception as e:
                msg = str(e)
                if ("network" in msg or "SSL" in msg) and attempt < 2:
                    print(f"[{slug}] 网络抖动,60s 重试", flush=True)
                    time.sleep(60)
                    continue
                print(f"[{slug}] 失败:{msg[:120]}", flush=True)
                break
    with sqlite3.connect(DB) as c:
        tot = c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls "
                        "WHERE experiment_id LIKE 'S5T%'").fetchone()[0]
    print(f"\nS5T 总耗 {tot} 对", flush=True)


if __name__ == "__main__":
    main()
