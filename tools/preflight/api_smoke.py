# -*- coding: utf-8 -*-
"""真实百度 API 预检：认证、地点、详情、步行路线与矩阵、台账。

运行:
    python3 tools/preflight/api_smoke.py

默认把预检调用写入临时账本，不污染 experiments/logs/calls.db。
"""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="15min_api_preflight_")
os.environ["LEDGER_DB"] = os.path.join(_TMP, "calls.db")
os.environ["CACHE_DB"] = os.path.join(_TMP, "cache.db")

from core import baidu_client as bc  # noqa: E402
from core import coord  # noqa: E402

EID = "PREFLIGHT-API-20260921"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    metrics: dict = field(default_factory=dict)


def _inside_china(lng: float, lat: float) -> bool:
    return 73.0 < lng < 136.0 and 3.0 < lat < 54.0


def check(name, condition, detail="", metrics=None):
    return Check(name, bool(condition), detail, metrics or {})


def _route_path_points(route: dict) -> List[tuple]:
    points = []
    for step in route.get("steps") or []:
        raw = step.get("path") or ""
        for pair in raw.split(";"):
            if not pair:
                continue
            parts = pair.split(",")
            if len(parts) >= 2:
                try:
                    points.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
    return points


def run_live_checks() -> dict:
    checks: List[Check] = []
    checks.append(check("ak_configured", bool(bc.AK), "BAIDU_MAP_AK present"
                        if bc.AK else "BAIDU_MAP_AK missing"))
    checks.append(check("sk_not_required_for_ak_mode", not bc.SK,
                        "BAIDU_MAP_SK empty; AK-only mode" if not bc.SK
                        else "BAIDU_MAP_SK configured (SN mode)"))

    # 1. 地理编码
    geo = bc.geocode("北京市昌平区回龙观", city="北京", experiment_id=EID)
    loc = (geo.data.get("result") or {}).get("location") or {}
    S = None
    if geo.ok and loc:
        S = (float(loc["lat"]), float(loc["lng"]))
    checks.append(check(
        "geocode", geo.ok and S is not None and _inside_china(S[1], S[0]),
        f"status={geo.status} message={geo.message}",
        {"lat": S[0] if S else None, "lng": S[1] if S else None,
         "precise": (geo.data.get("result") or {}).get("precise"),
         "confidence": (geo.data.get("result") or {}).get("confidence")},
    ))
    if S is None:
        return _finish(checks)

    # 2. 逆地理编码
    rev = bc.reverse_geocode(S, experiment_id=EID)
    formatted = (rev.data.get("result") or {}).get("formatted_address")
    checks.append(check(
        "reverse_geocode", rev.ok and bool(formatted),
        f"status={rev.status} message={rev.message}",
        {"formatted_address": formatted},
    ))

    # 3. POI 搜索
    search = bc.place_search("药店", location=S, radius=1000, scope=2,
                             page_size=5, page_num=0, experiment_id=EID)
    items = search.data.get("results") or []
    first = items[0] if items else None
    checks.append(check(
        "place_search", search.ok and bool(items) and all(
            it.get("uid") and it.get("name") and (it.get("location") or {}).get("lat") is not None
            for it in items),
        f"status={search.status} message={search.message}",
        {"total": search.data.get("total"), "returned": len(items),
         "first_uid": first.get("uid") if first else None,
         "first_name": first.get("name") if first else None},
    ))
    if first is None:
        return _finish(checks)

    # 4. POI 详情 (v3 可能在 results[0])
    uid = first["uid"]
    detail = bc.place_detail(uid, scope=2, experiment_id=EID)
    detail_item = bc.place_detail_item(detail)
    detail_info = (detail_item or {}).get("detail_info") or {}
    checks.append(check(
        "place_detail", detail.ok and detail_item is not None
        and detail_item.get("uid") == uid,
        f"status={detail.status} message={detail.message}",
        {"uid": uid, "name": (detail_item or {}).get("name"),
         "has_detail_info": bool(detail_info),
         "has_navi_location": bool(detail_info.get("navi_location")),
         "shop_hours_present": bool(detail_info.get("shop_hours"))},
    ))

    P = None
    floc = (first.get("location") or {})
    if floc.get("lat") is not None:
        P = (float(floc["lat"]), float(floc["lng"]))

    # 5. 单段步行 direction
    walk_sp = None
    if P is not None:
        walk_sp = bc.walking(S, P, experiment_id=EID)
        points = _route_path_points(walk_sp.route or {})
        checks.append(check(
            "walking_direction", walk_sp.ok and walk_sp.route is not None
            and (walk_sp.duration_s or 0) > 0 and (walk_sp.distance_m or 0) > 0
            and len(points) >= 2,
            f"status={walk_sp.status} message={walk_sp.message}",
            {"duration_s": walk_sp.duration_s, "distance_m": walk_sp.distance_m,
             "steps": len((walk_sp.route or {}).get("steps") or []),
             "path_points": len(points)},
        ))
    else:
        checks.append(check("walking_direction", False, "missing POI location"))

    # 6. 反向 direction,验证方向没有互相覆盖
    walk_ps = None
    if P is not None:
        walk_ps = bc.walking(P, S, experiment_id=EID)
        checks.append(check(
            "walking_reverse_direction", walk_ps.ok and walk_ps.route is not None
            and (walk_ps.duration_s or 0) > 0,
            f"status={walk_ps.status} message={walk_ps.message}",
            {"duration_s": walk_ps.duration_s, "distance_m": walk_ps.distance_m},
        ))

    # 7. 2x2 有方向矩阵,校验 origin-major 顺序与 direction 同源量级
    matrix = None
    if P is not None:
        matrix = bc.routematrix("walking", [S, P], [P, S], experiment_id=EID)
        mitems = bc.matrix_items(matrix)
        matrix_ok = matrix.ok and len(mitems) == 4
        if matrix_ok and walk_sp is not None and walk_ps is not None:
            def close(a, b):
                return a is not None and b is not None and abs(a - b) <= max(120.0, 0.25 * max(a, b))
            matrix_ok = (close(mitems[0]["duration_s"], walk_sp.duration_s)
                         and close(mitems[3]["duration_s"], walk_ps.duration_s))
        checks.append(check(
            "walking_matrix_directional", matrix_ok,
            f"status={matrix.status} message={matrix.message}",
            {"items": mitems,
             "forward_direction_s": walk_sp.duration_s if walk_sp else None,
             "reverse_direction_s": walk_ps.duration_s if walk_ps else None},
        ))
    else:
        checks.append(check("walking_matrix_directional", False, "missing POI location"))

    return _finish(checks)


def _finish(checks: List[Check]) -> dict:
    with sqlite3.connect(os.environ["LEDGER_DB"]) as c:
        rows = c.execute(
            "SELECT kind,status,message,cache_hit,n_pairs,duration_s,distance_m,raw_hash "
            "FROM calls WHERE experiment_id=? ORDER BY id", (EID,)).fetchall()
    row_dicts = [
        {"kind": r[0], "status": r[1], "message": r[2], "cache_hit": r[3],
         "n_pairs": r[4], "duration_s": r[5], "distance_m": r[6],
         "raw_hash": r[7]} for r in rows
    ]
    ledger_ok = bool(rows)
    # 成功 direction 的账本行必须记录 duration/distance。
    direction_rows = [r for r in row_dicts if r["kind"] == "walking" and r["status"] == 0]
    if direction_rows:
        ledger_ok = ledger_ok and all(
            r["duration_s"] is not None and r["distance_m"] is not None for r in direction_rows)
    matrix_rows = [r for r in row_dicts if r["kind"] == "matrix_walking"]
    if matrix_rows:
        ledger_ok = ledger_ok and all(r["n_pairs"] == 4 for r in matrix_rows)
    checks.append(check("ledger_recorded", ledger_ok,
                        f"rows={len(row_dicts)}",
                        {"rows": row_dicts}))
    return {
        "ok": all(c.ok for c in checks),
        "eid": EID,
        "ledger_db": os.environ["LEDGER_DB"],
        "checks": [c.__dict__ for c in checks],
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def main():
    ap = argparse.ArgumentParser(description="Live Baidu API preflight")
    ap.add_argument("--report", default="", help="optional JSON report path")
    args = ap.parse_args()

    result = run_live_checks()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
