"""E10-C · 弦走廊时间探针:相邻边界端点间的步行时间 → 障碍检测

原理:相邻射线端点 P_i、P_{i+1} 的步行时间 T(P_i→P_{i+1}) 若远超
"直线距离 / 典型步速" 的预期(绕行系数 ρ 爆表),则弦走廊内必有墙/河/铁路
—— 这正是"弦幻影"的成因,且语义比半径差判据准确:
半径差小 ≠ 无障碍(两侧端点被同一障碍挡住时半径差反而小)。

验证:对社区 A/B 的 16 边形,实测 16 条弦的端点间时间(共 32 对),
与已知弦违规名单(A:2 条;B 第 1 轮:9 条)对照,算检出率。
产出:experiments/results/e10c_chord.json
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at

EID = "E10C"
WALK_MS = 1.083                     # 3.9 km/h → m/s(E2 实测中位步速)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VIOL = {
    "A": {33.8, 191.2},
    "B": {33.8, 56.2, 146.2, 168.8, 191.2, 213.8, 258.8, 281.2, 348.8},
}


def endpoints(center, r16):
    b16 = sorted(r16)
    pts = [dest_at(center[1], center[0], b, r16[b]) for b in b16]
    return b16, pts


def flat(a, b):
    return math.hypot((a[0] - b[0]) * 111320,
                      (a[1] - b[1]) * 111320 * math.cos(math.radians(a[0])))


def main():
    A = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4.json"),
                       encoding="utf-8"))
    rA = {float(k): v for k, v in A["m4_radii"].items()}
    cA = tuple(A["center"])
    Bd = json.load(open(os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4b.json"),
                        encoding="utf-8"))
    allB = {float(k): v for k, v in Bd["radii_final"].items()}
    rB = {b: allB[b] for b in sorted(allB) if b in {i * 22.5 for i in range(16)}}
    cB = tuple(Bd["center"])

    out = {}
    for tag, center, r16 in (("A", cA, rA), ("B", cB, rB)):
        b16, pts = endpoints(center, r16)
        print(f"\n== 社区 {tag}:16 条弦的端点走廊探针 ==")
        print(f"{'弦方位':>7}{'半径差m':>8}{'直线m':>7}{'实测s':>7}{'预期s':>7}{'ρ':>6}  已知违规")
        rows = []
        for i in range(16):
            p1, p2 = pts[i], pts[(i + 1) % 16]
            mid_b = (b16[i] + b16[(i + 1) % 16]) / 2 % 360
            straight = flat(p1, p2)
            r = bc.direction("walking", p1, p2, experiment_id=EID)
            t = r.duration_s if r.ok else None
            exp = straight / WALK_MS
            rho = round(t / exp, 2) if t else None
            gap = round(abs(r16[b16[i]] - r16[b16[(i + 1) % 16]]))
            known = mid_b in VIOL[tag]
            rows.append({"chord_bearing": round(mid_b, 1), "gap_m": gap,
                         "straight_m": round(straight), "walk_s": t,
                         "expected_s": round(exp), "rho": rho, "known_violation": known})
            print(f"{mid_b:7.1f}{gap:8d}{straight:7.0f}{t or 0:7.0f}{exp:7.0f}"
                  f"{rho or 0:6.2f}  {'✗' if known else ''}")
            time.sleep(0.5)
        out[tag] = {"center": list(center), "chords": rows}

    # ---- 检出率分析:ρ 阈值扫描 ----
    print("\n== 检出率(以已知违规为标签)==")
    print(f"{'判据':<26}{'A:命中/误报':>12}{'B:命中/误报':>12}")
    for name, crit in [
        ("ρ>1.5", lambda c: c["rho"] and c["rho"] > 1.5),
        ("ρ>1.8", lambda c: c["rho"] and c["rho"] > 1.8),
        ("半径差>120m", lambda c: c["gap_m"] > 120),
        ("半径差>200m", lambda c: c["gap_m"] > 200),
        ("ρ>1.5 或 差>120m", lambda c: (c["rho"] and c["rho"] > 1.5) or c["gap_m"] > 120),
    ]:
        line = f"{name:<26}"
        for tag in ("A", "B"):
            cs = out[tag]["chords"]
            hit = sum(1 for c in cs if crit(c) and c["known_violation"])
            miss = sum(1 for c in cs if c["known_violation"]) - hit
            fa = sum(1 for c in cs if crit(c) and not c["known_violation"])
            line += f"{hit}/{miss}误{fa:>4}".rjust(12)
        print(line)

    json.dump(out, open(os.path.join(_ROOT, "experiments", "results", "e10_boundary", "e10c_chord.json"),
                        "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 experiments/results/e10c_chord.json")


if __name__ == "__main__":
    main()
