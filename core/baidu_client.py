"""百度地图 Web API 直连客户端。

上游契约对照 app-dxcyy98y3xtv/supabase/functions 的封装(去掉网关层,直连官方域名):

    /direction/v2/{mode}        行程规划 driving|riding|walking|transit
    /routematrix/v2/{mode}      批量算路 driving|riding|walking  ← E0.2/E3 的关键接口
    /place/v2/search            POI 检索(行政区划 / 周边圆形)——实测 /place/v3/search 端点 404,v2 可用
    /place/v3/detail            POI 详情
    /geocoding/v3/              地理编码
    /reverse_geocoding/v3/      逆地理编码

- AK 从根目录 .env 读取(服务端应用);
- 若开启 SN 校验,填 BAIDU_MAP_SK 即自动签名;
- 所有请求写入台账(core.ledger),配额可核算;
- 仅网络类错误重试(指数退避),业务错误(status != 0)原样返回,不重试。
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

from core.ledger import log_call

BASE = "https://api.map.baidu.com"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env() -> None:
    envf = os.path.join(_ROOT, ".env")
    if not os.path.exists(envf):
        return
    with open(envf, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
AK = os.environ.get("BAIDU_MAP_AK", "")
SK = os.environ.get("BAIDU_MAP_SK", "").strip()

_RETRYABLE = (urllib.error.URLError, TimeoutError, ConnectionError)


@dataclass
class ApiResult:
    ok: bool
    status: int
    message: str
    data: dict = field(default_factory=dict)
    latency_ms: int = 0

    def __bool__(self) -> bool:
        return self.ok


def _signed_params(path: str, params: dict) -> dict:
    """官方 SN 算法(lbsyun FAQ#sn计算算法),本机实测修正版:

        queryStr = path + '?' + k1=v1&k2=v2...   # GET:按 URL 出现顺序(插入序),值为【原文】
        sn = md5( quote_plus( quote(queryStr, safe) + SK ) )

    ⚠️ safe 列表用【无逗号版】"/:=&?#+!$;'@()*[]"(官方 FAQ 原文含 ','):
    实测(2026-08-24)direction/reverse_geocoding 的服务端按 RFC1738(http_build_query)
    重算签名,逗号会编码为 %2C;含逗号的官方 safe 只对旧版 geocoder 有效。
    sn 作为普通参数追加在 URL 末尾;sk 只参与计算,不出现在 URL。
    """
    params = dict(params)
    params["ak"] = AK
    if not SK:
        return params
    qs = path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    s1 = urllib.parse.quote(qs, safe="/:=&?#+!$;'@()*[]")
    sn = hashlib.md5(urllib.parse.quote_plus(s1 + SK).encode("utf-8")).hexdigest()
    params["sn"] = sn
    return params


def get(path: str, params: dict, *, kind: str, experiment_id: str,
        timeout: float = 10.0, retries: int = 2,
        o=None, d=None, n_pairs: int = 1,
        duration_s=None, distance_m=None) -> ApiResult:
    url = BASE + path + "?" + urllib.parse.urlencode(
        _signed_params(path, params))
    last: Optional[ApiResult] = None
    for attempt in range(retries + 1):
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "15min-life-cycle/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            latency = int((time.perf_counter() - t0) * 1000)
            status = int(body.get("status", -1))
            r = ApiResult(status == 0, status, str(body.get("message", "")), body, latency)
            log_call(experiment_id=experiment_id, kind=kind, o_lat=o and o[0], o_lng=o and o[1],
                     d_lat=d and d[0], d_lng=d and d[1], n_pairs=n_pairs,
                     latency_ms=latency, status=status, message=r.message,
                     duration_s=duration_s, distance_m=distance_m,
                     raw_hash=hashlib.md5(json.dumps(body, sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()[:16])
            return r
        except _RETRYABLE as e:            # 网络类错误:指数退避重试
            latency = int((time.perf_counter() - t0) * 1000)
            last = ApiResult(False, -1, f"network: {e}", {}, latency)
            log_call(experiment_id=experiment_id, kind=kind, o_lat=o and o[0], o_lng=o and o[1],
                     d_lat=d and d[0], d_lng=d and d[1], n_pairs=n_pairs,
                     latency_ms=latency, status=-1, message=str(e)[:120])
            if attempt < retries:
                time.sleep(1.5 ** attempt)
        except urllib.error.HTTPError as e:  # 4xx/5xx:读 body 里的业务信息,不重试
            latency = int((time.perf_counter() - t0) * 1000)
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                body = {}
            status = int(body.get("status", e.code))
            r = ApiResult(False, status, str(body.get("message") or e), body, latency)
            log_call(experiment_id=experiment_id, kind=kind, o_lat=o and o[0], o_lng=o and o[1],
                     d_lat=d and d[0], d_lng=d and d[1], n_pairs=n_pairs,
                     latency_ms=latency, status=status, message=r.message[:120])
            return r
    return last


def _ll(pt) -> str:
    return f"{pt[0]},{pt[1]}"   # (lat,lng) 元组 → "纬度,经度"(百度要求 lat 在前)


# ---------- 行程规划(direction v2,单对) ----------

def direction(mode: str, origin, destination, *, experiment_id: str, **extra) -> ApiResult:
    params = {"origin": _ll(origin), "destination": _ll(destination), **extra}
    r = get(f"/direction/v2/{mode}", params, kind=mode, experiment_id=experiment_id,
            o=origin, d=destination)
    if r.ok:
        route = (r.data.get("result") or {}).get("routes") or [{}]
        r.duration_s = route[0].get("duration")
        r.distance_m = route[0].get("distance")
    return r


def walking(origin, destination, *, experiment_id: str) -> ApiResult:
    return direction("walking", origin, destination, experiment_id=experiment_id)


# ---------- 批量算路(routematrix v2,1 请求 n 对) ----------

def routematrix(mode: str, origins: List[tuple], destinations: List[tuple], *,
                experiment_id: str, **extra) -> ApiResult:
    params = {
        "origins": "|".join(_ll(p) for p in origins),
        "destinations": "|".join(_ll(p) for p in destinations),
        "output": "json", **extra,
    }
    r = get(f"/routematrix/v2/{mode}", params, kind=f"matrix_{mode}",
            experiment_id=experiment_id, o=origins[0], d=destinations[-1],
            n_pairs=len(origins) * len(destinations))
    return r


def matrix_items(r: ApiResult) -> list:
    """routematrix 结果展开:[{duration_s, distance_m, ...}]"""
    return [
        {
            "duration_s": it.get("duration", {}).get("value"),
            "distance_m": it.get("distance", {}).get("value"),
        }
        for it in (r.data.get("result") or [])
    ]


# ---------- POI(place v3) ----------

def place_search(query: str, *, region: str = None, location: tuple = None,
                 radius: int = None, scope: int = 2, page_size: int = 20,
                 page_num: int = 0, experiment_id: str = "", **extra) -> ApiResult:
    params = {"query": query, "scope": scope, "page_size": page_size,
              "page_num": page_num, "output": "json", **extra}
    if region:
        params["region"] = region
    if location:
        params["location"] = _ll(location)
        if radius:
            params["radius"] = radius
    return get("/place/v2/search", params, kind="poi", experiment_id=experiment_id,
               o=location, n_pairs=1)


# ---------- 地理编码 ----------

def geocode(address: str, *, city: str = None, ret_coordtype: str = None,
            experiment_id: str = "") -> ApiResult:
    params = {"address": address, "output": "json"}
    if city:
        params["city"] = city
    if ret_coordtype:
        params["ret_coordtype"] = ret_coordtype
    return get("/geocoding/v3/", params, kind="geocode", experiment_id=experiment_id)


def reverse_geocode(location: tuple, *, coordtype: str = None,
                    experiment_id: str = "") -> ApiResult:
    params = {"location": _ll(location), "output": "json"}
    if coordtype:
        params["coordtype"] = coordtype
    return get("/reverse_geocoding/v3/", params, kind="reverse_geocode",
               experiment_id=experiment_id, o=location)
