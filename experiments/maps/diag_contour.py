# -*- coding: utf-8 -*-
"""诊断:重建场/粗网格 15min 等值线到底有没有画出来、画在哪里(零 API)。"""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import griddata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from experiments.maps.plot_maps import TH, load_field, to_wgs, key  # noqa: E402
from core.coord import dest_at  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES = os.path.join(ROOT, "experiments", "results")
MAPDIR = os.path.join(RES, "maps")


def diag(slug, fname):
    d = json.load(open(os.path.join(RES, fname), encoding="utf-8"))
    center = tuple(d["center"])
    radii = {float(k): v for k, v in d["radii"].items()}
    field = load_field(center)
    pts = list(field.keys())
    clat, clng = to_wgs(center)
    print(f"\n== {slug} == 场 {len(field)} 点, 边界半径 "
          f"{min(radii.values()):.0f}~{max(radii.values()):.0f} m")

    # --- 重建场 50m 分辨率(与 plot_maps 相同) ---
    fx = np.array([to_wgs(p)[1] for p in pts])
    fy = np.array([to_wgs(p)[0] for p in pts])
    ft = np.array([field[p] for p in pts])
    gx, gy = [], []
    for i in range(-23, 24):
        for j in range(-23, 24):
            p = dest_at(center[1], center[0],
                        math.degrees(math.atan2(j, i)) if (i or j) else 0,
                        math.hypot(i, j) * 50)
            la, ln = to_wgs(p)
            gx.append(ln)
            gy.append(la)
    gz = griddata(np.column_stack([fx, fy]), ft,
                  np.column_stack([gx, gy]), method="linear")
    # 与 plot_maps 相同的弦约束
    def r_at2(brg):
        ks = sorted(radii)
        import bisect as _b
        i2 = _b.bisect_right(ks, brg) - 1
        b0, b1 = ks[i2 % len(ks)], ks[(i2 + 1) % len(ks)]
        db_ = (b1 - b0) % 360 or 360
        t2 = ((brg - b0) % 360) / db_
        return radii[b0] * (1 - t2) + radii[b1] * t2

    for k2, (ln_, la_) in enumerate(zip(gx, gy)):
        dd = math.hypot((la_ - clat) * 111320,
                        (ln_ - clng) * 111320 * math.cos(math.radians(clat)))
        bb = math.degrees(math.atan2((ln_ - clng) * math.cos(math.radians(clat)),
                                     la_ - clat)) % 360
        if dd > r_at2(bb) + 80:
            gz[k2] = np.nan
    n_nan = int(np.isnan(gz).sum())
    print(f"重建格 2209 点中 NaN(凸包外) {n_nan}")
    fig, ax = plt.subplots(figsize=(8, 8), dpi=150)
    Xr = np.array(gx).reshape(47, 47)
    Yr = np.array(gy).reshape(47, 47)
    Zr = np.ma.masked_invalid(np.array(gz).reshape(47, 47))
    cs = ax.contour(Xr, Yr, Zr, levels=[TH], colors=["k"], linewidths=[2.6])
    segs = cs.allsegs[0]
    radii_of_pts = []
    for s in segs:
        for lng, lat in s:
            dn = math.hypot((lat - clat) * 111320,
                            (lng - clng) * 111320 * math.cos(math.radians(clat)))
            radii_of_pts.append(dn)
    if radii_of_pts:
        print(f"重建场 900s 等值线: {len(segs)} 段, 径向范围 "
              f"{min(radii_of_pts):.0f}~{max(radii_of_pts):.0f} m")
        # 每 30° 方位的黑线半径 vs 成品 r_at(检测虚假深凹)
        brgs = []
        for s in segs:
            for lng, lat in s:
                dn = math.hypot((lat - clat) * 111320,
                                (lng - clng) * 111320
                                * math.cos(math.radians(clat)))
                bb = math.degrees(math.atan2(
                    (lng - clng) * math.cos(math.radians(clat)),
                    lat - clat)) % 360
                brgs.append((bb, dn))
        line = "方位: 黑线半径/成品半径 |"
        for b30 in range(0, 360, 30):
            cand = [dn for bb, dn in brgs if min((bb - b30) % 360, (b30 - bb) % 360) < 8]
            if cand:
                line += f" {b30:03d}°:{min(cand):.0f}/{r_at2(b30):.0f}"
        print(line)
        bad = [(b30, min(dn for bb, dn in brgs
                         if min((bb - b30) % 360, (b30 - bb) % 360) < 8))
               for b30 in range(0, 360, 30)
               if any(min((bb - b30) % 360, (b30 - bb) % 360) < 8 for bb, _ in brgs)
               and min(dn for bb, dn in brgs
                       if min((bb - b30) % 360, (b30 - bb) % 360) < 8)
               < r_at2(b30) - 120]
        print("深凹(比成品近>120m):", bad if bad else "无")
    else:
        print("重建场 900s 等值线: 0 段! (范围内全是<900 或 全是NaN?)")
        v = np.array(gz)
        print(f"  场值范围 {np.nanmin(v):.0f}~{np.nanmax(v):.0f} s, "
              f">900 占比 {np.mean(v[~np.isnan(v)] > 900):.2%}")
    ax.plot(clng, clat, "r*", markersize=15)
    ax.set_aspect(1 / math.cos(math.radians(clat)))
    ax.set_title(f"{slug}: 重建场 15min 线(黑) 段数={len(segs)}")
    out = os.path.join(MAPDIR, f"_diag_{slug}.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"已存 {out}")

    # --- 200m 实测网格线(同 plot_maps grid_contour) ---
    sp = 200
    half = 1000
    n = int(2 * half // sp)
    idx = range(-n // 2, n // 2 + 1)
    X, Y, Z = [], [], []
    for i2 in idx:
        lat0, lng0 = dest_at(center[1], center[0], 0, i2 * sp)
        rx, ry, rz = [], [], []
        for j2 in idx:
            p = dest_at(lng0, lat0, 90, j2 * sp)
            la, ln = to_wgs(p)
            rx.append(ln)
            ry.append(la)
            rz.append(field.get(key(p), np.nan))
        X.append(rx)
        Y.append(ry)
        Z.append(rz)
    Zm = np.ma.masked_invalid(np.array(Z))
    fig2, ax2 = plt.subplots(figsize=(8, 8), dpi=150)
    cs2 = ax2.contour(np.array(X), np.array(Y), Zm, levels=[TH],
                      colors=["#8c564b"], linewidths=[2.0], linestyles=["--"])
    segs2 = cs2.allsegs[0]
    rr = []
    for s in segs2:
        for lng, lat in s:
            rr.append(math.hypot((lat - clat) * 111320,
                                 (lng - clng) * 111320
                                 * math.cos(math.radians(clat))))
    print(f"{sp}m 实测网格 900s 线: {len(segs2)} 段, "
          + (f"径向 {min(rr):.0f}~{max(rr):.0f} m" if rr else "0 段"))
    zz = np.array(Z, dtype=float)
    print(f"  网格值 {np.nanmin(zz):.0f}~{np.nanmax(zz):.0f} s, "
          f">900 占比 {np.mean(zz[~np.isnan(zz)] > 900):.2%}")
    ax2.plot(clng, clat, "r*", markersize=15)
    ax2.set_aspect(1 / math.cos(math.radians(clat)))
    ax2.set_title(f"{slug}: {sp}m 网格 15min 线(棕) 段数={len(segs2)}")
    out2 = os.path.join(MAPDIR, f"_diag_{slug}_grid.png")
    fig2.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print(f"已存 {out2}")


if __name__ == "__main__":
    diag("chengdu", "e10_boundary/e10x_chengdu.json")
    diag("harbin", "e10_boundary/e10x_harbin.json")
