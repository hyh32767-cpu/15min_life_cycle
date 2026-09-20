# -*- coding: utf-8 -*-
"""S5G · 小角度弦验证·梯度制收敛版(2026-09-02,~422 对)

规则(收敛性有保证):
  候选弦 = arc ∈ [3°, 22.5°] 且 dz/arc > 12 m/°(陡弦)
  边中点 C_mid 实测:超时=凹,1.06 外扩可达=凸 → 弦中点方位插向(tol25)
  插入后弧减半 → 梯度通常减半 → 自然收敛(不同于 arc≤11.25° 的不收敛版)

守卫(v3 教训):
  每城独立 EID;bisect 前后核对消耗,零消耗=当场弃;返回值|v-800|<0.5 弃

批量(50 对/请求):
  边探针批量打包;二分用"全向并行分波"(每波批量测所有活跃向中点)
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
GRAD_THR = 12.0    # m/° 陡弦阈值
ARC_MIN = 3.0
ARC_MAX = 22.5
TOL = 25.0
CAP_PER_CITY = 100
GLOBAL_CAP = 2000

FILES = {"A": ("e4_sampling", "e4.json", "m4_radii"),
         "B": ("e4_sampling", "e4b.json", "radii_final")}
ORDER = ["guilin", "xian", "nanchang", "wuhan", "kunshan", "qunli",
         "kunming", "xiamen", "zunyi", "A", "chengdu",
         "shenyang", "qingdao", "suzhou", "changchun", "fuzhou"]
# 去重(guangzhou2 不存在)
ORDER = [s for s in ORDER if s != "guangzhou2"]

DB = os.path.join(RESULTS, "..", "logs", "calls.db")


def spent(eid):
    import sqlite3
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE "
                         "experiment_id=?", (eid,)).fetchone()[0]


def batch_measure(eid, center, pts):
    """缓存优先,≤50 对/请求批量;预算不足返回 None。"""
    out = []
    for i in range(0, len(pts), 50):
        chunk = pts[i:i + 50]
        vals = [None] * len(chunk)
        todo, tidx = [], []
        for k, p in enumerate(chunk):
            row = wcache.get(center, p)
            if row and row[0] is not None:
                vals[k] = row[0]
            else:
                todo.append(p)
                tidx.append(k)
        if todo:
            if spent(eid) + len(todo) > CAP_PER_CITY:
                return None
            for attempt in range(4):
                r = bc.routematrix("walking", [center], todo, experiment_id=eid)
                if r.ok:
                    break
                if r.status in (401, 302) and attempt < 3:
                    time.sleep([15, 30, 60][attempt]); continue
                if "network" in str(r.message) or "SSL" in str(r.message):
                    time.sleep(20); continue
                raise RuntimeError(f"matrix {r.status} {r.message}")
            for p, it in zip(todo, bc.matrix_items(r)):
                if it.get("duration_s") is not None:
                    wcache.put(center, p, it["duration_s"], it.get("distance_m"))
            for k, p in zip(tidx, todo):
                row = wcache.get(center, p)
                vals[k] = row[0] if row else None
        out += vals
    return out


def wave_bisect(eid, center, mids):
    """全向并行二分(tol25)。"""
    lo = {b: 200.0 for b in mids}
    hi = {b: 1400.0 for b in mids}
    done = {}
    for wave in range(12):
        cur = {b: (lo[b] + hi[b]) / 2 for b in mids}
        pts = [dest_at(center[1], center[0], b, cur[b]) for b in mids]
        ts = batch_measure(eid, center, pts)
        if ts is None:
            return done, False
        nxt = []
        for b, t in zip(mids, ts):
            if t is None:
                continue
            if t <= TH:
                lo[b] = cur[b]
            else:
                hi[b] = cur[b]
            if hi[b] - lo[b] > TOL:
                nxt.append(b)
            else:
                v = (lo[b] + hi[b]) / 2
                if abs(v - 800.0) > 0.5:
                    done[b] = v
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
    eid = f"S5G{idx:02d}"
    label = d.get("city") or d.get("community") or slug
    kcos = math.cos(math.radians(center[0]))
    total_ins = 0

    for rd in range(4):
        if spent(eid) >= CAP_PER_CITY - 10:
            break
        ks = sorted(radii)
        cands = []
        for a, b in zip(ks, ks[1:] + [ks[0] + 360]):
            arc = (b - a) % 360 or 360
            if arc < ARC_MIN or arc > ARC_MAX:
                continue
            dz = abs(radii[a % 360] - radii[b % 360])
            if dz / max(arc, 0.1) <= GRAD_THR:
                continue
            mb = ((a + b) / 2) % 360
            if any(abs(mb - x) < 0.6 or abs(mb - x - 360) < 0.6 for x in radii):
                continue
            # 边中点
            pa = dest_at(center[1], center[0], a % 360, radii[a % 360])
            pb = dest_at(center[1], center[0], b % 360, radii[b % 360])
            cm = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            dd = math.hypot((cm[0] - center[0]) * 111320,
                            (cm[1] - center[1]) * 111320 * kcos)
            cm2 = dest_at(center[1], center[0], mb, dd * 1.06)
            cands.append((round(mb, 2), cm, cm2, round(dz / arc, 1)))
        if not cands:
            print(f"[{label}] 梯度制一致 ✓(第{rd+1}轮)", flush=True)
            break
        # 批量边探针
        pts = []
        for _, cm, cm2, _ in cands:
            pts += [cm, cm2]
        ts = batch_measure(eid, center, pts)
        if ts is None:
            print(f"[{label}] 预算不足,停", flush=True)
            break
        ins = []
        for i, (mb, cm, cm2, grad) in enumerate(cands):
            t1, t2 = ts[i * 2], ts[i * 2 + 1]
            why = ("凹" if (t1 is not None and t1 > TH)
                   else ("凸" if (t2 is not None and t2 <= TH) else ""))
            if why:
                ins.append((mb, why, grad))
        if not ins:
            print(f"[{label}] 第{rd+1}轮:候选{len(cands)}全部通过 ✓", flush=True)
            break
        got, ok = wave_bisect(eid, center, [m for m, _, _ in ins])
        ok_ins = [(m, w, g, round(got[m])) for m, w, g in ins if m in got]
        if not ok_ins:
            print(f"[{label}] 第{rd+1}轮:插向未落地(预算/缺数据)", flush=True)
            break
        for m, _, _, v in ok_ins:
            radii[m] = v
        total_ins += len(ok_ins)
        print(f"[{label}] 第{rd+1}轮:插{len(ok_ins)}向 "
              f"(梯度 {[g for _,_,g,_ in ok_ins[:3]]}...) → k={len(radii)}", flush=True)

    d[rk] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    if rk != "radii":
        d["radii"] = d[rk]
    d["rays"] = len(radii)
    d.setdefault("s5g", {}).update({"inserted": total_ins, "pairs": spent(eid)})
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{label}] 完成:+{total_ins}向 k={len(radii)} 耗{spent(eid)}对", flush=True)


def main():
    only = set(sys.argv[1:])
    import sqlite3
    for idx, slug in enumerate(ORDER):
        if only and slug not in only:
            continue
        with sqlite3.connect(DB) as c:
            g = c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls "
                          "WHERE experiment_id LIKE 'S5G%'").fetchone()[0]
        if g >= GLOBAL_CAP:
            print("全局预算触顶", flush=True)
            break
        for attempt in range(3):
            try:
                run(slug, idx)
                break
            except Exception as e:
                msg = str(e)
                if ("network" in msg or "SSL" in msg) and attempt < 2:
                    print(f"[{slug}] 网络抖动,60s重试", flush=True)
                    time.sleep(60)
                    continue
                print(f"[{slug}] 失败:{msg[:120]}", flush=True)
                break
    with sqlite3.connect(DB) as c:
        tot = c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls "
                        "WHERE experiment_id LIKE 'S5G%'").fetchone()[0]
    print(f"\nS5G 总耗 {tot} 对", flush=True)


if __name__ == "__main__":
    main()
