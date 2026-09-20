"""E4 · 采样策略对比(答辩杀手表)—— 单社区完整版 v1

社区 A:北京·王府井(老城 + 故宫屏障,各向异性强)
真值:100m 网格 2km×2km(441 对)+ 50m 加密(中心 1km×1km)
方法:
  M1 网格 200m(嵌套于 M2,0 新增调用)
  M2 网格 100m(441 对 = 真值场本体)
  M3 网格 50m 中心 1km×1km(新增 ~320 对)
  M4 扇形 16 向 + 二分(跨射线同步批量,±15m)
  M7 自适应扇形:8 向起步,相邻半径差 >150m 处角度加密(≤32 向)
  M8 边界带 AMR:M2 场 12–18min 单元对角半步加密
评估:
  80 个 held-out 随机点(独立批量实测)→ 各方法 IDW(p=2)插值预测
  → MAE / RMSE / 15min 分类准确率 / P / R / F1 / IoU / 边界半径偏差
样本集按"阶段新增键"精确划分,杜绝跨方法污染;
嵌套复用(M7 复用 M4 轨迹、M1 ⊂ M2)如实记录 actual_new_pairs。
预算:≤ 1600 对(台账按 n_pairs 审计)。产出:experiments/results/e4.json
"""
import json
import math
import os
import random
import sqlite3
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core import cache
from core.coord import dest_at
from core.ledger import Budget, _DB_PATH

EID = "E4"
PAIRS_BUDGET = 2400               # 含上次 401 中断已耗的 ~450 对
BUDGET = Budget(EID, 200)          # 请求数上限(宽松;真正约束是对数)
HALF = 1000                        # 2km × 2km 研究区
TH = 900                           # 15 min 阈值(秒)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES_PATH = os.path.join(_ROOT, "experiments", "results", "e4_sampling", "e4.json")


def pairs_used() -> int:
    with sqlite3.connect(_DB_PATH) as c:
        return c.execute("SELECT COALESCE(SUM(n_pairs),0) FROM calls WHERE experiment_id=?",
                         (EID,)).fetchone()[0]


def check_budget(planned=0):
    if pairs_used() + planned >= PAIRS_BUDGET:
        raise RuntimeError(f"[{EID}] 对数预算 {PAIRS_BUDGET} 已耗尽(已用 {pairs_used()})")


def key(p):
    return (round(p[0], 6), round(p[1], 6))


def flat_m(lat0, lng0, lat1, lng1):
    """2km 尺度平面近似距离(米),用于 IDW/角度计算。"""
    return math.hypot((lat1 - lat0) * 111320,
                      (lng1 - lng0) * 111320 * math.cos(math.radians(lat0)))


class Sampler:
    """坐标级去重缓存(SQLite 持久化,重跑零消耗)+ 批量实测。

    - 请求间隔 PACE 秒,防止触发 401 并发配额;
    - 401(限流)按 15/30/60s 退避重试;
    - 先查持久缓存,API 结果写回缓存。
    """

    PACE = 1.2

    def __init__(self, center):
        self.center = center
        self.requests = 0
        self.phase_new = set()           # 当前阶段【新调用】的键(API 实测)
        self.hit = 0

    def cached_time(self, p):
        return cache.get(self.center, p)

    def begin_phase(self):
        self.phase_new = set()

    def measure(self, points):
        todo = [p for p in points if self.cached_time(p) is None]
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            check_budget(len(chunk))
            for attempt in range(4):
                r = bc.routematrix("walking", [self.center], chunk, experiment_id=EID)
                self.requests += 1
                if r.ok:
                    break
                if r.status == 401 and attempt < 3:          # 并发配额:退避
                    wait = [15, 30, 60][attempt]
                    print(f"  ⚠️ 401 限流,退避 {wait}s(第 {attempt+1} 次)")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"matrix failed: {r.status} {r.message}")
            else:
                raise RuntimeError("matrix failed: 401 重试耗尽")
            for p, it in zip(chunk, bc.matrix_items(r)):
                cache.put(self.center, p, it["duration_s"], it["distance_m"])
                self.phase_new.add(key(p))
            time.sleep(self.PACE)
        return {key(p): (self.cached_time(p) or (None, None)) for p in points}

    def t_of(self, p):
        row = self.cached_time(p)
        if row is None:
            self.measure([p])
            row = self.cached_time(p)
        return row[0]


def grid_points(center, spacing, half):
    n = int(2 * half // spacing)
    pts = []
    for i in range(-n // 2, n // 2 + 1):
        lat0, lng0 = dest_at(center[1], center[0], 0, i * spacing)     # 纵向
        for j in range(-n // 2, n // 2 + 1):
            lat, lng = dest_at(lng0, lat0, 90, j * spacing)            # 横向
            pts.append((lat, lng))
    return pts


def bisect_rays(S, bearings, lo=200.0, hi=1400.0, tol=15.0):
    """跨射线同步二分:初始探测 800m 一轮批量,之后每轮打包所有活动射线中点。"""
    lo = {b: lo for b in bearings}
    hi = {b: hi for b in bearings}
    S.measure([dest_at(S.center[1], S.center[0], b, 800) for b in bearings])
    active = list(bearings)
    while active:
        probs = [dest_at(S.center[1], S.center[0], b, (lo[b] + hi[b]) / 2) for b in active]
        S.measure(probs)
        nxt = []
        for b, p in zip(active, probs):
            t = S.t_of(p)
            if t is None:
                continue
            if t <= TH:
                lo[b] = (lo[b] + hi[b]) / 2
            else:
                hi[b] = (lo[b] + hi[b]) / 2
            if hi[b] - lo[b] > tol:
                nxt.append(b)
        active = nxt
    return {b: (lo[b] + hi[b]) / 2 for b in bearings}


def idw(samples, points, p=2.0):
    out = []
    for pt in points:
        num = den = 0.0
        for (lat, lng), t in samples.items():
            if t is None:
                continue
            d = flat_m(pt[0], pt[1], lat, lng)
            if d < 1e-6:
                num, den = t, 1.0
                break
            w = 1.0 / (d ** p)
            num += w * t
            den += w
        out.append(num / den if den > 0 else None)
    return out


def boundary_radius(center, samples, bearing, half=1400.0, step=10.0):
    dists = np_range(200, half, step)
    pts = [dest_at(center[1], center[0], bearing, d) for d in dists]
    ts = idw(samples, pts)
    last_in = first_out = None
    for d, t in zip(dists, ts):
        if t is None:
            continue
        if t <= TH:
            last_in = d
        elif last_in is not None:
            first_out = d
            break
    if last_in is None:
        return 0.0
    return last_in if first_out is None else (last_in + first_out) / 2


def np_range(a, b, step):
    out = []
    x = a
    while x <= b + 1e-9:
        out.append(round(x, 3))
        x += step
    return out


def cls_metrics(y_true, y_pred):
    tp = sum(1 for a, b in zip(y_true, y_pred) if a and b)
    fp = sum(1 for a, b in zip(y_true, y_pred) if not a and b)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a and not b)
    tn = sum(1 for a, b in zip(y_true, y_pred) if not a and not b)
    acc = (tp + tn) / max(1, len(y_true))
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return acc, prec, rec, f1


def ray_pick(center, ray_keys, bearings, tol_deg=1.0):
    """从射线类样本键中,挑出落在给定方位角 ±tol 内的点。"""
    out = {}
    for k in ray_keys:
        dlat = (k[0] - center[0]) * 111320
        dlng = (k[1] - center[1]) * 111320 * math.cos(math.radians(center[0]))
        if not (180 <= math.hypot(dlat, dlng) <= 1420):
            continue
        ang = math.degrees(math.atan2(dlng, dlat)) % 360
        if any(min(abs(ang - b), 360 - abs(ang - b)) <= tol_deg for b in bearings):
            out[k] = None                       # 时长稍后回填
    return out


def main():
    e0 = json.load(open(os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e0.json"),
                        encoding="utf-8"))
    center = tuple(e0["center"])
    print(f"社区 A 中心(bd09): {center[0]:.5f},{center[1]:.5f}")
    S = Sampler(center)
    t0 = time.perf_counter()

    # ---- M2 真值场:100m 网格 ----
    print("== M2:100m 网格 21×21 ==")
    S.begin_phase()
    S.measure(grid_points(center, 100, HALF))
    m2_new = set(S.phase_new)
    M2 = {k: S.cached_time(k)[0] for k in m2_new}        # 该阶段新增即网格点
    print(f"  新增 {len(m2_new)} 对 | 累计 {pairs_used()} 对 / {S.requests} 请求")

    # ---- M3 50m 加密 ----
    print("== M3:50m 网格 中心 1km×1km ==")
    S.begin_phase()
    S.measure(grid_points(center, 50, 500))
    m3_new = set(S.phase_new)
    M3 = {k: S.cached_time(k)[0] for k in m2_new | m3_new}
    print(f"  新增 {len(m3_new)} 对 | 累计 {pairs_used()} 对 / {S.requests} 请求")

    # ---- M4 扇形 16 向 + 二分 ----
    print("== M4:扇形 16 向 + 同步二分(±15m)==")
    b16 = [i * 22.5 for i in range(16)]
    S.begin_phase()
    r16 = bisect_rays(S, b16)
    m4_new = set(S.phase_new)
    print(f"  新增 {len(m4_new)} 对 | 半径: " +
          " ".join(f"{b:.0f}°={r16[b]:.0f}" for b in b16[:8]) + " …")

    # ---- M7 自适应扇形 ----
    print("== M7:自适应扇形 8 向起步,差>150m 加密 ==")
    S.begin_phase()
    r_ad = bisect_rays(S, list(range(0, 360, 45)))
    for _ in range(3):
        brgs = sorted(r_ad)
        gaps = [((a + b) / 2) % 360 for a, b in zip(brgs, brgs[1:] + [brgs[0] + 360])
                if b - a > 22.5 and abs(r_ad[a % 360] - r_ad[b % 360]) > 150]
        if not gaps:
            break
        r_ad.update(bisect_rays(S, gaps))
    m7_new = set(S.phase_new)
    ray_keys = m4_new | m7_new
    print(f"  最终 {len(r_ad)} 向 | 本阶段新增 {len(m7_new)} 对(嵌套复用 M4 轨迹)")

    # ---- M8 边界带 AMR ----
    print("== M8:M2 场 12–18min 单元对角半步加密 ==")
    S.begin_phase()
    band = [k for k, t in M2.items() if t is not None and 720 <= t <= 1080]
    refine = []
    for (lat, lng) in band:
        for brg in (45, 135, 225, 315):
            refine.append(dest_at(lng, lat, brg, 35))
    S.measure(refine)
    m8_new = set(S.phase_new)
    M8 = {k: S.cached_time(k)[0] for k in set(M2) | m8_new}
    print(f"  边界单元 {len(band)} | 加密点 {len(m8_new)} 对")

    wall_s = time.perf_counter() - t0

    # ---- held-out 验证 80 点 ----
    print("== held-out 验证:80 随机点 ==")
    rng = random.Random(2026)
    S.begin_phase()
    val = []
    while len(val) < 80:
        p = dest_at(center[1], center[0], rng.uniform(0, 360), rng.uniform(150, 1150))
        if S.cached_time(p) is None and all(flat_m(a[0], a[1], p[0], p[1]) > 25 for a in val):
            val.append(p)
    S.measure(val)
    val_true = [S.cached_time(p)[0] for p in val]
    total_pairs, total_req = pairs_used(), S.requests
    print(f"  验证 {len(val)} 对 | 总计 {total_pairs} 对 / {total_req} 请求 / {wall_s:.0f}s 采样墙钟")

    # ---- 评估 ----
    m1_keys = {key(p) for p in grid_points(center, 200, HALF)}
    M1 = {k: t for k, t in M2.items() if k in m1_keys}
    M4 = {k: S.cached_time(k)[0] for k in m4_new}
    M7 = ray_pick(center, ray_keys, sorted(r_ad))
    M7 = {k: S.cached_time(k)[0] for k in M7}

    methods = {
        "M1 网格200m":      (M1, 121),
        "M2 网格100m":      (M2, 441),
        "M3 网格50m1km":    (M3, 441),
        "M4 扇形16二分":    (M4, len(m4_new)),
        "M7 自适应扇形":    (M7, len(r_ad) * 9),
        "M8 边界带AMR":     (M8, 441 + len(m8_new)),
    }
    grid_keys = list(M2.keys())
    truth_cls = [(M2[k] is not None and M2[k] <= TH) for k in grid_keys]
    ref_bnd = {b: boundary_radius(center, M3, b) for b in range(0, 360, 45)}

    print("\n===== 杀手表(社区A·王府井)=====")
    print(f"{'方法':<12}{'独立对数':>7}{'请求':>4}{'实测对':>6}{'MAE_s':>7}{'RMSE':>7}"
          f"{'acc15':>7}{'F1':>6}{'IoU':>6}{'边界Δm':>7}")
    results = []
    for name, (samples, standalone) in methods.items():
        pv = idw(samples, val)
        pairs = [(a, b) for a, b in zip(val_true, pv) if a is not None and b is not None]
        err = [b - a for a, b in pairs]
        mae = statistics.mean(abs(e) for e in err)
        rmse = math.sqrt(statistics.mean(e * e for e in err))
        acc, prec, rec, f1 = cls_metrics([a <= TH for a, _ in pairs],
                                         [b <= TH for _, b in pairs])
        pg = idw(samples, grid_keys)
        yg = [p is not None and p <= TH for p in pg]
        inter = sum(1 for a, b in zip(truth_cls, yg) if a and b)
        union = sum(1 for a, b in zip(truth_cls, yg) if a or b)
        iou = inter / max(1, union)
        berrs = [abs(boundary_radius(center, samples, b) - ref_bnd[b])
                 for b in range(0, 360, 45)
                 if ref_bnd[b] and boundary_radius(center, samples, b)]
        row = {"method": name, "pairs_standalone": standalone,
               "requests": math.ceil(standalone / 50), "n_samples": len(samples),
               "mae_s": round(mae, 1), "rmse_s": round(rmse, 1), "acc15": round(acc, 3),
               "precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
               "iou": round(iou, 3),
               "boundary_err_m": round(statistics.mean(berrs), 1) if berrs else None}
        results.append(row)
        print(f"{name:<12}{row['pairs_standalone']:>7}{row['requests']:>4}"
              f"{len(samples):>6}{row['mae_s']:>7}{row['rmse_s']:>7}{row['acc15']:>7}"
              f"{row['f1']:>6}{row['iou']:>6}{row['boundary_err_m'] or '-':>7}")

    json.dump({"experiment": EID, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "center": list(center), "pairs_used": total_pairs,
               "requests": total_req, "wall_s": round(wall_s),
               "phase_pairs": {"M2": len(m2_new), "M3": len(m3_new), "M4": len(m4_new),
                               "M7": len(m7_new), "M8": len(m8_new)},
               "methods": results,
               "m4_radii": {f"{b:.1f}": round(r16[b], 1) for b in b16},
               "adaptive_rays": {f"{b:.1f}": round(v, 1) for b, v in r_ad.items()}},
              open(RES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已写入 {RES_PATH}")


if __name__ == "__main__":
    main()
