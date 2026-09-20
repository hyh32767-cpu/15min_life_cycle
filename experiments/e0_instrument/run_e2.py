"""E2 · 测量仪器特性:确定性 / 对称性 / 射线单调性

  E2.1 确定性:6 对 (o,d) × 3 轮(轮间隔 20s),步行 duration 波动 → 底噪 σ̂
  E2.2 对称性:6 对 f(o,d) vs f(d,o)
  E2.3 射线单调性:8 方向 × 200–1400m 每 100m(13 点/向),
       优先 routematrix 批量;批量服务未开通时单发降级

断点续跑:每个方向完成即增量保存 e2.json;重跑时跳过已完成部分。
预算:≤ 500 请求(台账计数,含网络失败重试)。产出:experiments/results/e2.json
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at
from core.ledger import Budget

EID = "E2"
BUDGET = Budget(EID, 500)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RES_PATH = os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e2.json")
BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315]
DISTS = list(range(200, 1500, 100))          # 200..1400, 13 点
N_PAIR_REPEAT = 6
ROUNDS = 3


def load_partial():
    if os.path.exists(RES_PATH):
        try:
            return json.load(open(RES_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(res):
    os.makedirs(os.path.dirname(RES_PATH), exist_ok=True)
    json.dump(res, open(RES_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def load_center():
    e0p = os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e0.json")
    c = json.load(open(e0p, encoding="utf-8")).get("center") if os.path.exists(e0p) else None
    if c:
        return tuple(c)
    r = bc.geocode("北京市东城区王府井大街", city="北京", experiment_id=EID)
    loc = r.data["result"]["location"]
    return (loc["lat"], loc["lng"])


def ray_durations(center, brg, use_matrix):
    """一个方向上 13 个距离点的 duration;优先批量,不可用则单发降级。

    单发时若连续 3 次网络级失败(DNS 抖动),该方向剩余点标记 None 并提前返回,
    避免重试风暴烧穿预算。
    """
    dests = [dest_at(center[1], center[0], brg, dd) for dd in DISTS]
    if use_matrix[0]:
        BUDGET.check()
        r = bc.routematrix("walking", [center], dests, experiment_id=EID)
        if r.ok:
            return [i["duration_s"] for i in bc.matrix_items(r)], \
                   [i["distance_m"] for i in bc.matrix_items(r)]
        use_matrix[0] = False
        print(f"  ⚠️ 批量不可用(status={r.status})→ 改用单发降级")
    durs, dists, fails = [], [], 0
    for d_ in dests:
        if fails >= 3:
            durs.append(None); dists.append(None); continue
        BUDGET.check()
        r = bc.walking(center, d_, experiment_id=EID)
        if r.ok:
            durs.append(r.duration_s); dists.append(r.distance_m); fails = 0
        else:
            durs.append(None); dists.append(None); fails += 1
            time.sleep(2)
        time.sleep(0.15)
    return durs, dists


def main():
    res = load_partial()
    res.setdefault("experiment", EID)
    res["ts_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    center = tuple(res.get("center") or load_center())
    res["center"] = list(center)
    print(f"中心(bd09): {center[0]:.5f},{center[1]:.5f}")

    # ---- E2.1 确定性(可续:已存在则跳过) ----
    if "determinism" not in res:
        print(f"== E2.1 确定性({N_PAIR_REPEAT} 对 × {ROUNDS} 轮,轮间隔 20s) ==")
        pairs = [dest_at(center[1], center[0], b, 300 + 180 * i)
                 for i, b in enumerate([10, 70, 130, 190, 250, 310])]
        series = [[] for _ in pairs]
        for rnd in range(ROUNDS):
            for i, d_ in enumerate(pairs):
                BUDGET.check()
                r = bc.walking(center, d_, experiment_id=EID)
                if r.ok:
                    series[i].append(r.duration_s)
            if rnd < ROUNDS - 1:
                time.sleep(20)
        noises = [statistics.pstdev(s) for s in series if len(s) >= 2]
        if noises:
            sigma = max(noises)
            print(f"  各对 duration 标准差: {[round(n,2) for n in noises]}")
            print(f"  底噪 σ̂ ≈ {sigma:.2f}s → 二分停机阈值建议 |Δt| < {max(2*sigma, 1):.0f}s")
            res["determinism"] = {"per_pair_std_s": [round(n, 2) for n in noises],
                                  "sigma_hat_s": round(sigma, 2)}
        save(res)
    else:
        print("== E2.1 已有数据,跳过 ==")

    # ---- E2.2 对称性 ----
    if "symmetry_delta_s" not in res:
        print("== E2.2 对称性 f(o,d) vs f(d,o) ==")
        pairs = [dest_at(center[1], center[0], b, 300 + 180 * i)
                 for i, b in enumerate([10, 70, 130, 190, 250, 310])]
        sym = []
        for d_ in pairs:
            BUDGET.check()
            fwd = bc.walking(center, d_, experiment_id=EID)
            BUDGET.check()
            bwd = bc.walking(d_, center, experiment_id=EID)
            if fwd.ok and bwd.ok:
                sym.append(round(bwd.duration_s - fwd.duration_s, 1))
        if sym:
            print(f"  Δ(反向-正向, 秒): {sym}  mean={statistics.mean(sym):+.1f}s")
            res["symmetry_delta_s"] = sym
        save(res)
    else:
        print("== E2.2 已有数据,跳过 ==")

    # ---- E2.3 射线单调性(逐方向续跑) ----
    print(f"== E2.3 射线单调性(8 方向 × {len(DISTS)} 距离) ==")
    rays = {int(k): v for k, v in res.get("rays", {}).items()}
    speeds = []
    use_matrix = ["matrix_blocked" not in res]
    for brg in BEARINGS:
        if brg in rays:
            continue
        durs, dists = ray_durations(center, brg, use_matrix)
        if not use_matrix[0]:
            res["matrix_blocked"] = True
        rays[brg] = {"durations_s": durs, "route_distances_m": dists}
        viol = []
        for i in range(1, len(durs)):
            if durs[i] is not None and durs[i-1] is not None and durs[i] < durs[i-1] - 1:
                viol.append({"dist_m": DISTS[i], "prev_s": durs[i-1], "cur_s": durs[i]})
        rays[brg]["violations"] = viol
        ok = [d for d in durs if d is not None]
        print(f"  {brg:3d}°: {len(ok)}/{len(DISTS)} 点"
              + (f"  {DISTS[0]}m={round(ok[0])}s ... {DISTS[-1]}m={round(ok[-1])}s" if ok else "")
              + (f"  viol×{len(viol)}" if viol else ""))
        res["rays"] = {str(k): v for k, v in rays.items()}
        save(res)          # 每个方向完成即保存

    # ---- 汇总 ----
    for v in rays.values():
        for ds, du in zip(v["route_distances_m"], v["durations_s"]):
            if ds and du:
                speeds.append(ds / du * 3.6)
    n_viol = sum(len(v["violations"]) for v in rays.values())
    if speeds:
        lo, hi = min(speeds), max(speeds)
        print(f"  隐含步速: min={lo:.1f} max={hi:.1f} 中位={statistics.median(speeds):.1f} km/h(合理带 3–6)")
        res["implied_speed_kmh"] = {"min": round(lo, 1), "max": round(hi, 1),
                                    "median": round(statistics.median(speeds), 1)}
    print(f"  单调性违反点合计: {n_viol}")
    res["monotonicity_violations_total"] = n_viol
    save(res)
    print(f"\n结果已写入 {RES_PATH}")


if __name__ == "__main__":
    main()
