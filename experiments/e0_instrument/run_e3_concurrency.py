# -*- coding: utf-8 -*-
"""E3C - 并发/限流系统测绘(v2,配额恢复后)

档位:2 / 4 / 8 / 16 QPS(用户额度 50 请求/3s ~= 16.7 QPS,16 档贴近边界)。
每档 40 个单对 routematrix 请求(=160 对),按目标速率匀速发出(起点对齐调度)。
记录:逐请求延迟/状态码;汇总 P50/P95 延迟、成功率、限流命中数。
点选取:哈尔滨中心不同方位/距离的唯一未缓存点(强制真实调用)。
产出:results/e0_instrument/e3_concurrency.json;结论写入 docs/01 附录。
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import baidu_client as bc
from core.coord import dest_at

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EID = "E3C"
CENTER = (45.787628862747844, 126.64736136918812)   # 哈尔滨道外
TIERS = [2, 4, 8, 16]
N = 40
SLEEP_BETWEEN = 30


def pt(i):
    """唯一探测点:方位 0-359 均布,距离 250+i*11.7m,避开已缓存轨迹点。"""
    b = (i * 8.99) % 360
    return dest_at(CENTER[1], CENTER[0], b, 250 + i * 11.7)


def main():
    results = {}
    idx = 0
    for qps in TIERS:
        interval = 1.0 / qps
        lat, statuses = [], {}
        t0 = time.time()
        print(f"\n== 档位 {qps} QPS × {N} 请求(间隔 {interval:.3f}s)==")
        for i in range(N):
            sched = t0 + i * interval
            dt = sched - time.time()
            if dt > 0:
                time.sleep(dt)
            d = pt(idx)
            idx += 1
            s = time.time()
            r = bc.routematrix("walking", [CENTER], [d], experiment_id=EID)
            el = (time.time() - s) * 1000
            lat.append(round(el))
            statuses[r.status] = statuses.get(r.status, 0) + 1
            if r.status != 0:
                print(f"  !! 第{i+1} 个请求 status={r.status} {r.message}")
        ok = statuses.get(0, 0)
        sl = sorted(lat)
        p50 = sl[len(sl) // 2]
        p95 = sl[int(0.95 * len(sl))]
        results[qps] = {"n": N, "ok": ok, "statuses": statuses,
                        "latency_p50_ms": p50, "latency_p95_ms": p95,
                        "mean_ms": round(sum(lat) / len(lat))}
        print(f"  成功 {ok}/{N} | P50 {p50}ms P95 {p95}ms | 状态 {statuses}")
        if qps != TIERS[-1]:
            time.sleep(SLEEP_BETWEEN)

    fp = os.path.join(ROOT, "experiments", "results", "e0_instrument", "e3_concurrency.json")
    json.dump({"limit_declared": "50 req / 3s (~16.7 QPS)", "tiers": results},
              open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已写入 {fp}")


if __name__ == "__main__":
    main()
