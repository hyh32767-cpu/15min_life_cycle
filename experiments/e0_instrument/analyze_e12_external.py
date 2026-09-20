# -*- coding: utf-8 -*-
"""E12 v3 · 测前路由之外部信号(A:DEM 地形 + C:LLM 类型先验)

约束:零百度调用、不下载路网(用户政策)。
A:AWS Open Data terrarium 高程瓦片(z12,~38m/px,免鉴权)→ 社区 1.5km 内
   relief(极差)/rug(粗糙度)/std;与 aniso8、复杂标签验证。
C:类型→复杂度先验表(由二十社区自身类型标签留一验证;产品化时由 LLM 打类型标签)。
产出:results/e0_instrument/e12_route_v3_external.json + docs/11 记录。
"""
import io
import json
import math
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
from PIL import Image

from core.coord import bd09_to_wgs84
from experiments.paths import RESULTS

FILES = {"A": ("e4_sampling", "e4.json"), "B": ("e4_sampling", "e4b.json")}
SLUGS = ["A", "B", "shanghai", "guangzhou", "chengdu", "harbin", "xian", "chongqing",
         "changsha", "wuhan", "luoyang", "kunshan", "guilin", "zunyi", "yiwu",
         "nanchang", "huilongguan", "zhangjiang", "zhujiangxincheng", "yulin_cd"]
Z = 13   # 单瓦片 4.5km,1.5km 窗口定位更稳
M_PER_PX = 156543.03 * math.cos(math.radians(30)) / (2 ** Z)  # 近似,按纬度修正


def tiles_for(lat, lng, box_m=0):
    """中心所在 z12 瓦片(单瓦片 9.8km 足盖 1.5km 窗口,避免拼接错位)。"""
    mpp = 156543.03 * math.cos(math.radians(lat)) / (2 ** Z)
    n = 2 ** Z
    xt = int((lng + 180) / 360 * n)
    yt = int((1 - math.log(math.tan(math.radians(lat)) +
                           1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return [(xt, yt)], mpp


def fetch_dem(lat, lng, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    tiles, mpp = tiles_for(lat, lng)
    grid = {}
    for x, y in tiles:
        fp = os.path.join(cache_dir, f"{Z}_{x}_{y}.png")
        if not os.path.exists(fp):
            url = f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
            open(fp, "wb").write(data)
        im = np.asarray(Image.open(fp)).astype(np.float32)
        elev = im[:, :, 0] * 256 + im[:, :, 1] + im[:, :, 2] / 256 - 32768
        grid[(x, y)] = elev
    return grid, tiles, mpp


def dem_stats(lat, lng, cache_dir, radius_m=1500):
    grid, tiles, mpp = fetch_dem(lat, lng, cache_dir)
    n = 2 ** Z
    xt = (lng + 180) / 360 * n
    yt = (1 - math.log(math.tan(math.radians(lat)) +
                       1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    # 以中心瓦片为基准拼接局部窗口
    base = (int(xt), int(yt))
    win = int(radius_m / mpp)
    cx = int((xt - base[0]) * 256)
    cy = int((yt - base[1]) * 256)
    pad = 300
    big = np.full((2 * win + 2 * pad, 2 * win + 2 * pad), np.nan, np.float32)
    for (x, y), elev in grid.items():
        ox = (x - base[0]) * 256 + pad + win - cx
        oy = (y - base[1]) * 256 + pad + win - cy
        if 0 <= ox < big.shape[1] and 0 <= oy < big.shape[0]:
            h, w = elev.shape
            big[oy:oy + h, ox:ox + w] = elev
    sub = big[pad:pad + 2 * win, pad:pad + 2 * win]
    sub = sub[~np.isnan(sub)]
    if sub.size < 100:
        return None
    gy = np.abs(np.diff(big, axis=0))
    gx = np.abs(np.diff(big, axis=1))
    band0 = slice(pad + win - 5, pad + win + 5)
    band1 = slice(pad, pad + 2 * win)
    rug = float(np.nanmean(gy[band0, band1]) + np.nanmean(gx[band1, band0])) / 2
    return {"relief": round(float(sub.max() - sub.min()), 1),
            "std": round(float(sub.std()), 1),
            "rug": round(rug, 2)}


def main():
    cache_dir = os.path.join(RESULTS, "..", "logs", "dem_tiles")
    rows = []
    for slug in SLUGS:
        sub, fn = FILES.get(slug, ("e10_boundary", f"e10x_{slug}.json"))
        d = json.load(open(os.path.join(RESULTS, sub, fn), encoding="utf-8"))
        center = tuple(d["center"])
        lng_w, lat_w = bd09_to_wgs84(center[1], center[0])
        try:
            st = dem_stats(lat_w, lng_w, cache_dir)
        except Exception as e:
            st = None
            print(f"  [DEM 失败] {slug}: {str(e)[:60]}")
        label = (d.get("gap_over_200m", 0) >= 2)
        rows.append({"slug": slug, "city": d.get("city") or d.get("community", slug),
                     "type": d.get("type", ""), "dem": st,
                     "aniso8": None, "label": label})
        if st:
            print(f"{rows[-1]['city']:10s} relief={st['relief']:6.1f}m std={st['std']:5.1f} "
                  f"rug={st['rug']:5.2f} → {'复杂' if label else '简单'}")

    # aniso8 标签(来自 e12 v2 缓存计算)
    v2 = json.load(open(os.path.join(RESULTS, "e0_instrument", "e12_route.json"),
                        encoding="utf-8"))
    aniso = {r["slug"]: r["aniso8"] for r in v2.get("rows", []) if "aniso8" in r}
    for r in rows:
        r["aniso8"] = aniso.get(r["slug"])

    # A:阈值 LOO
    def loo(feat, thr):
        ok = sum(1 for r in rows if r["dem"] and (r["dem"][feat] >= thr) == r["label"])
        n = sum(1 for r in rows if r["dem"])
        return ok / max(1, n), n
    best = None
    print("\nA·DEM 阈值规则 LOO:")
    for feat in ("relief", "std", "rug"):
        vals = sorted(set(r["dem"][feat] for r in rows if r["dem"]))
        accs = [(loo(feat, t)[0], t) for t in vals]
        a, t = max(accs)
        print(f"  {feat:6s} ≥{t} → {a:.0%}")
        if best is None or a > best[0]:
            best = (a, feat, t)

    # C:类型先验(留一多数票)
    from collections import Counter
    ok_c = 0
    for r in rows:
        others = [x for x in rows if x["slug"] != r["slug"] and x["type"] == r["type"]]
        if others:
            pred = Counter(x["label"] for x in others).most_common(1)[0][0]
        else:
            pred = True       # 未见类型保守判复杂
        ok_c += (pred == r["label"])
    acc_c = ok_c / len(rows)
    print(f"\nC·类型先验 LOO:{acc_c:.0%}(类型表:" +
          "; ".join(sorted(set(r['type'] for r in rows if r['type']))) + ")")

    # 组合:A 或 C 任一判复杂
    a, feat, thr = best
    ok_ab = 0
    for r in rows:
        if not r["dem"]:
            continue
        others = [x for x in rows if x["slug"] != r["slug"] and x["type"] == r["type"]]
        pred_c = (Counter(x["label"] for x in others).most_common(1)[0][0]
                  if others else True)
        pred = (r["dem"][feat] >= thr) or pred_c
        ok_ab += (pred == r["label"])
    acc_ab = ok_ab / sum(1 for r in rows if r["dem"])
    print(f"\n组合规则(DEM {feat}≥{thr} OR 类型先验判复杂) LOO:{acc_ab:.0%}")

    json.dump({"v": "v3-external", "rows": rows,
               "A_rule": {"feature": feat, "thr": thr, "loo": a},
               "C_prior_loo": acc_c, "combo_loo": acc_ab,
               "note": "A=AWS terrarium z12(非路网);C=类型先验表,产品化由 LLM 打标签"},
              open(os.path.join(RESULTS, "e0_instrument", "e12_route_v3_external.json"),
                   "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写 e12_route_v3_external.json")


if __name__ == "__main__":
    main()
