# -*- coding: utf-8 -*-
"""E4MID - 四城 mid 残留违规清零(run_new4 三轮上限的续跑,v2)

v2 修正:预算截断时被跳过的探针≠"一致"——必须区分"干净"与"没测完"。
首轮全弦(旧探针命中缓存零成本),后续轮只扫新插入射线的相邻弦(E10 原设计)。
诚实产出:mid_clear={rounds, probes, new_pairs, cleared, residual};
cleared=True 当且仅当整轮扫描无截断且零违规。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from experiments.e10_boundary.run_e10_cities import CityRunner
from experiments.e4_sampling.run_e4 import grid_points, key

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TH = 900
EID = "E4MID"
CAPS = {"changsha": 500, "xian": 300, "wuhan": 350, "chongqing": 350}
RES = os.path.join(ROOT, "experiments", "results", "e10_boundary")


def run(slug):
    fp = os.path.join(RES, f"e10x_{slug}.json")
    d = json.load(open(fp, encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    R = CityRunner(EID, center, cap=CAPS[slug])
    print(f"\n===== {d['city']} 射线 {len(radii)}(上限 {CAPS[slug]} 对)=====")

    rounds, probes, cleared, residual, truncated = 0, 0, False, -1, False
    new_bearings = None
    for rd in range(10):
        rounds = rd + 1
        ks = sorted(radii)
        chords = list(zip(ks, ks[1:] + [ks[0] + 360]))
        if new_bearings is not None:
            chords = [(a, b) for a, b in chords
                      if any(abs(((a + b) / 2) % 360 - nb) < 1e-6 for nb in new_bearings)]
        bad, skipped = [], 0
        for a, b in chords:
            mb = ((a + b) / 2) % 360
            probe = R.endpoint(mb, R.r_at(mb, radii) * 0.97)
            R.measure([probe])
            if R.left() <= 0:
                skipped += 1
                truncated = True
                break
            t = R.t_of(probe)
            probes += 1
            if t is not None and t > TH:
                bad.append(mb)
        if truncated or skipped:
            print(f"  第{rounds}轮预算截断({skipped} 个探针未测)——如实记 uncleared")
            residual = -1
            break
        if not bad:
            print(f"  第{rounds}轮扫描一致 ✓(累计探针 {probes},新耗 {R.used()} 对)")
            cleared, residual = True, 0
            break
        print(f"  第{rounds}轮:{len(bad)} 弦违规 {['%.1f°' % x for x in bad]} -> 插向重二分")
        residual = len(bad)
        radii.update(R.bisect(bad))
        new_bearings = bad
        if R.left() <= 0:
            truncated = True
            print("  !! 重二分后预算触顶")
            break

    # 重算指标(真值格走缓存,零 API)
    spacing = d.get("metrics", {}).get("truth_spacing") or 200
    g = grid_points(center, spacing, 1000)
    truth = {}
    for p in g:
        row = R.cached(p)
        if row:
            truth[key(p)] = row[0]
    truth = {k: v for k, v in truth.items() if v is not None}
    keys = list(truth)
    yt = [truth[k] <= TH for k in keys]
    yp = [R.polar(k)[0] < R.r_at(R.polar(k)[1], radii) for k in keys]
    inter = sum(1 for a, b2 in zip(yt, yp) if a and b2)
    union = sum(1 for a, b2 in zip(yt, yp) if a or b2)
    m = {"fp": sum(1 for a, b2 in zip(yt, yp) if b2 and not a),
         "fn": sum(1 for a, b2 in zip(yt, yp) if a and not b2),
         "iou": round(inter / max(1, union), 3), "truth_n": len(keys),
         "truth_spacing": spacing}
    print(f"  IoU {d.get('metrics', {}).get('iou')} -> {m['iou']}(n={m['truth_n']})")

    d["rays"] = len(radii)
    d["anisotropy"] = round(max(radii.values()) / max(1e-9, min(radii.values())), 2)
    d["radius_range"] = [round(min(radii.values())), round(max(radii.values()))]
    d["mid_probes"] = d.get("mid_probes", 0) + probes
    d["metrics"] = m
    d["mid_clear"] = {"rounds": rounds, "probes": probes, "new_pairs": R.used(),
                      "cleared": cleared, "residual": residual, "truncated": truncated}
    d["radii"] = {f"{b:.2f}": round(v, 1) for b, v in sorted(radii.items())}
    json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  已更新 {fp}(射线 {len(radii)},cleared={cleared},residual={residual})")


def main():
    for slug in CAPS:
        try:
            run(slug)
        except Exception as e:
            print(f"[{slug}] 失败:{str(e)[:150]}")


if __name__ == "__main__":
    main()
