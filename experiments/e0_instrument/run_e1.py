"""E1 · 坐标系一致性:转换往返误差 + 混用偏移量化

  E1.1 bd09→gcj02→wgs84→gcj02→bd09 全链往返,20 个点(纯本地计算,零配额)
  E1.2 混用偏移:同一个物理点,正确 bd09 喂 API vs 拿 wgs84 数值当 bd09 喂 API,
       对比 步行路线距离/时长 与 逆地理地址(4 次 API)

依赖 E0 的 center(读 e0.json;若无则先用地理编码取一次)。
预算:≤ 12 请求。产出:experiments/results/e1.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import (bd09_to_gcj02, gcj02_to_bd09, gcj02_to_wgs84,
                        haversine, wgs84_to_gcj02)
from core.ledger import Budget, quota_used

EID = "E1"
BUDGET = Budget(EID, 30)   # 含调试期的重复执行调用
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def roundtrip_errors(center):
    """E1.1:全链往返闭合误差(米)。"""
    import random
    rng = random.Random(7)
    errs = []
    for i in range(20):
        if i == 0 and center:
            lat, lng = center
        else:
            lat, lng = rng.uniform(39.8, 39.95), rng.uniform(116.3, 116.5)
        lng2, lat2 = bd09_to_gcj02(lng, lat)
        lng3, lat3 = gcj02_to_wgs84(lng2, lat2)
        lng4, lat4 = wgs84_to_gcj02(lng3, lat3)
        lng5, lat5 = gcj02_to_bd09(lng4, lat4)
        errs.append(haversine(lng, lat, lng5, lat5))
    return errs


def main():
    # E0 结果里取中心点
    center = None
    e0p = os.path.join(_ROOT, "experiments", "results", "e0_instrument", "e0.json")
    if os.path.exists(e0p):
        c = json.load(open(e0p, encoding="utf-8")).get("center")
        if c:
            center = tuple(c)
    if center is None:
        BUDGET.check()
        r = bc.geocode("北京市东城区王府井大街", city="北京", experiment_id=EID)
        loc = r.data["result"]["location"]
        center = (loc["lat"], loc["lng"])

    print("== E1.1 坐标全链往返(20 点,本地计算) ==")
    errs = roundtrip_errors(center)
    import statistics
    print(f"  闭合误差: max={max(errs):.6f} m  mean={statistics.mean(errs):.6f} m  (要求 < 1 m)")
    res = {"experiment": EID, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "roundtrip_max_m": max(errs), "roundtrip_mean_m": statistics.mean(errs),
           "pass_lt_1m": max(errs) < 1.0}

    # 偏移幅度:bd09 vs wgs84 数值差
    print("== E1.2 坐标混用偏移量化 ==")
    from core.coord import bd09_to_wgs84
    wlng, wlat = bd09_to_wgs84(center[1], center[0])
    offset_m = haversine(center[1], center[0], wlng, wlat)
    print(f"  同一物理点 bd09 数值 vs wgs84 数值:偏移 {offset_m:.1f} m")
    res["numeric_offset_m"] = round(offset_m, 1)

    # 用 API 量化后果:目标点 = 中心正东 800m(bd09)
    from core.coord import dest_at
    p_bd = dest_at(center[1], center[0], 90, 800)               # (lat,lng) bd09
    p_wg = bd09_to_wgs84(p_bd[1], p_bd[0])                       # 该点的 wgs84 经纬度
    mixed = (p_wg[1], p_wg[0])                                   # 错把 wgs84 数值当 bd09 用
    mix_offset = haversine(p_bd[1], p_bd[0], mixed[1], mixed[0])

    BUDGET.check()
    r_ok = bc.walking(center, p_bd, experiment_id=EID)
    BUDGET.check()
    r_mix = bc.walking(center, mixed, experiment_id=EID)
    BUDGET.check()
    a_ok = bc.reverse_geocode(p_bd, experiment_id=EID)
    BUDGET.check()
    a_mix = bc.reverse_geocode(mixed, experiment_id=EID)

    addr_ok = (a_ok.data.get("result") or {}).get("formatted_address", "?") if a_ok.ok else "?"
    addr_mix = (a_mix.data.get("result") or {}).get("formatted_address", "?") if a_mix.ok else "?"
    print(f"  落点偏移 {mix_offset:.0f} m")
    if r_ok.ok and r_mix.ok:
        dd = r_mix.distance_m - r_ok.distance_m
        dt = r_mix.duration_s - r_ok.duration_s
        print(f"  路线:正确 {r_ok.distance_m}m/{r_ok.duration_s}s  混用 {r_mix.distance_m}m/{r_mix.duration_s}s"
              f"  → Δ距离 {dd:+.0f}m Δ时长 {dt:+.0f}s")
        res["route"] = {"correct": [r_ok.distance_m, r_ok.duration_s],
                        "mixed": [r_mix.distance_m, r_mix.duration_s],
                        "delta_m": dd, "delta_s": dt}
    else:
        print(f"  路线调用失败: correct={r_ok.status} mixed={r_mix.status}")
    print(f"  地址:正确 → {addr_ok}")
    print(f"        混用 → {addr_mix}")
    res["address_correct"], res["address_mixed"] = addr_ok, addr_mix
    res["landing_offset_m"] = round(mix_offset)

    d = os.path.join(_ROOT, "experiments", "results", "e0_instrument")
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(os.path.join(d, "e1.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n结果已写入 experiments/results/e1.json")


if __name__ == "__main__":
    main()
