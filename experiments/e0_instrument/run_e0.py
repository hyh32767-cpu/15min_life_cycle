"""E0 · API 能力基线探查 → 《仪器规格表》

子实验:
  E0.5 地理编码往返(先行:为后续实验取真实 bd09 坐标)
  E0.1 步行单发延迟画像(40 次,随机方位/距离 200–1500m)
  E0.2 批量算路能力探查(尺寸 2/5/10/25/50)+ 单发 vs 批量一致性(8 对)
  E0.4 POI 检索画像(5 民生类目,周边 2km,首页)

预算:≤ 130 请求(台账自动计数,超限 abort)
产出:experiments/results/e0.json
"""
import json
import math
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at, haversine
from core.ledger import Budget

EID = "E0"
BUDGET = Budget(EID, 320)   # 含 SN 调试期历史调用,今日补全批量/POI 子实验
ADDRS = ["北京市东城区天安门", "北京市东城区王府井大街", "北京市东城区北京站",
         "北京市朝阳区朝阳公园", "北京市海淀区中关村", "北京市西城区金融街"]
POI_CATS = {"医疗": "医院", "教育": "小学", "购物": "菜市场", "药店": "药店", "养老": "养老院"}
RESULTS = {"experiment": EID, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(math.ceil(p / 100 * len(xs))) - 1)]


def main():
    # ---- E0.5 地理编码往返 ----
    print("== E0.5 地理编码往返 ==")
    geo = {}
    for addr in ADDRS:
        BUDGET.check()
        r = bc.geocode(addr, city="北京", experiment_id=EID)
        if r.ok:
            loc = r.data["result"]["location"]
            geo[addr] = (loc["lat"], loc["lng"])
            rr = bc.reverse_geocode((loc["lat"], loc["lng"]), experiment_id=EID)
            back = (rr.data.get("result") or {}).get("formatted_address", "?") if rr.ok else "?"
            print(f"  {addr} -> {loc['lat']:.5f},{loc['lng']:.5f} -> {back}")
        else:
            print(f"  {addr} FAIL status={r.status} {r.message}")
    RESULTS["geocode"] = {a: list(p) for a, p in geo.items()}
    if not geo:
        json.dump(RESULTS, open_result(), ensure_ascii=False)
        return

    center = geo["北京市东城区王府井大街"]
    print(f"  实验中心(王府井, bd09): {center[0]:.5f},{center[1]:.5f}")
    RESULTS["center"] = list(center)

    # ---- E0.1 步行延迟画像 ----
    print("== E0.1 步行单发延迟画像 (n=40) ==")
    lat, errs = [], []
    rng = random.Random(42)
    pairs = []
    for _ in range(40):
        BUDGET.check()
        brg, dist = rng.uniform(0, 360), rng.uniform(200, 1500)
        dst = dest_at(center[1], center[0], brg, dist)
        r = bc.walking(center, dst, experiment_id=EID)
        if r.ok:
            lat.append(r.latency_ms)
            pairs.append((dst, r.duration_s, r.distance_m))
        else:
            errs.append((r.status, r.message))
    if lat:
        print(f"  成功 {len(lat)}/{40 + len(errs)}  P50={pct(lat,50)}ms P95={pct(lat,95)}ms "
              f"P99={pct(lat,99)}ms 均值={statistics.mean(lat):.0f}ms")
        durs = [p[1] for p in pairs if p[1]]
        print(f"  时长范围: {min(durs):.0f}s ~ {max(durs):.0f}s (示例 {len(durs)} 条)")
    RESULTS["walk_latency"] = {"n_ok": len(lat), "n_err": len(errs),
                               "p50": pct(lat, 50), "p95": pct(lat, 95), "p99": pct(lat, 99),
                               "mean": round(statistics.mean(lat)) if lat else None}
    RESULTS["walk_errors"] = errs[:5]

    # ---- E0.2 批量算路能力 ----
    print("== E0.2 批量算路能力探查 (routematrix/v2/walking) ==")
    batch = []
    blocked = False
    for n in (2, 5, 10, 25, 50):
        BUDGET.check()
        dests = [dest_at(center[1], center[0], 90, 200 + 40 * i) for i in range(n)]  # 正东射线
        r = bc.routematrix("walking", [center], dests, experiment_id=EID)
        items = bc.matrix_items(r) if r.ok else []
        ok_n = len([i for i in items if i["duration_s"] is not None])
        batch.append({"n": n, "ok": r.ok, "status": r.status, "returned": ok_n,
                      "latency_ms": r.latency_ms, "message": r.message[:60]})
        print(f"  请求 {n:2d} 对: ok={r.ok} 返回 {ok_n:2d} 条  {r.latency_ms}ms  {'' if r.ok else r.message[:50]}")
        if r.status == 211:                      # 服务未勾选 → 停止烧调用,标记 BLOCKED
            blocked = True
            print("  ⚠️ 211 = 批量算路服务未在控制台勾选(或签名规则未知)→ 本子实验 BLOCKED")
            break
        time.sleep(0.3)
    RESULTS["batch"] = batch
    RESULTS["batch_blocked"] = blocked
    max_ok = max((b["n"] for b in batch if b["ok"] and b["returned"] == b["n"]), default=0)

    # 一致性:同样 8 对,单发 vs 批量
    cons = []
    if max_ok >= 8:
        dests = [dest_at(center[1], center[0], 90, 250 + 50 * i) for i in range(8)]
        singles = []
        for d_ in dests:
            BUDGET.check()
            r = bc.walking(center, d_, experiment_id=EID)
            singles.append(r.duration_s if r.ok else None)
        r = bc.routematrix("walking", [center], dests, experiment_id=EID)
        multis = [i["duration_s"] for i in bc.matrix_items(r)] if r.ok else []
        cons = [None if a is None or b is None else round(b - a, 1)
                for a, b in zip(singles, multis)]
        print(f"  单发 vs 批量 duration 差(秒): {cons}")
    RESULTS["consistency_single_minus_batch_s"] = cons
    RESULTS["batch_max_ok"] = max_ok

    # ---- E0.4 POI 检索画像 ----
    print("== E0.4 POI 检索画像 (place/v3/search 周边 2km) ==")
    poi = {}
    for cat, kw in POI_CATS.items():
        BUDGET.check()
        r = bc.place_search(kw, location=center, radius=2000, page_size=20,
                            experiment_id=EID)
        res = r.data.get("results") or [] if r.ok else []
        poi[cat] = {"ok": r.ok, "status": r.status, "n_page1": len(res),
                    "total": r.data.get("total"), "message": r.message[:60]}
        print(f"  {cat}({kw}): total={r.data.get('total') if r.ok else '-'} 首页 {len(res)} 条"
              f"{'' if r.ok else '  ' + r.message[:40]}")
    RESULTS["poi"] = poi

    json.dump(RESULTS, open_result(), ensure_ascii=False, indent=1)
    print(f"\n结果已写入 {os.path.join('experiments', 'results', 'e0.json')}")


def open_result():
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "experiments", "results", "e0_instrument")
    os.makedirs(d, exist_ok=True)
    return open(os.path.join(d, "e0.json"), "w", encoding="utf-8")


if __name__ == "__main__":
    main()
