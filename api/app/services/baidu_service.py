# -*- coding: utf-8 -*-
"""产品级百度服务:缓存、账本、live 统一出口。

路由层只依赖本服务的领域结果;百度参数、缓存 key、账本和错误映射
都收在这里."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import os
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from core.baidu_client import route_leg_summary
from core.coord import gcj02_to_bd09, wgs84_to_bd09
from core.corridor_evidence import compute_corridor_evidence
from core.detour import keep_route_detour
from core.ratelimit import AdaptiveRateLimiter, Singleflight, WindowRateLimiter
from core.route_samples import sample_geometry

from ..adapters.baidu.client import BaiduAdapter
from ..config import ConfigError, Settings
from ..models.common import Coord
from ..models.domain import PlaceRef
from ..storage.api_cache import ApiCache, request_hash, response_hash
from ..storage.ledger import ProductLedger, new_trace_id
from .corridor import point_to_polyline_m, sample_centers
from .errors import ServiceError

_LIVE_TTL_S = 6 * 3600


def to_baidu_bd09(coord: Coord) -> Tuple[Coord, Optional[str]]:
    """F61：百度请求唯一出口。WGS84/GCJ02 先转 BD09 再发请求、再算缓存 key。

    返回 (bd09_coord, converted_from)：未转换时 converted_from 为 None，
    供调用方在响应里保留追踪。未知 crs 直接报错，不静默当 BD09。
    """
    crs = str(getattr(coord.crs, "value", coord.crs) or "BD09").upper()
    if crs == "BD09":
        return coord, None
    if crs == "WGS84":
        lng, lat = wgs84_to_bd09(coord.lng, coord.lat)
        return Coord(lng=lng, lat=lat, crs="BD09"), "WGS84"
    if crs == "GCJ02":
        lng, lat = gcj02_to_bd09(coord.lng, coord.lat)
        return Coord(lng=lng, lat=lat, crs="BD09"), "GCJ02"
    raise ServiceError("VALIDATION_ERROR", f"不支持的坐标系: {crs}", http_status=422)


@dataclass
class GatewayResult:
    interface: str
    body: Dict[str, Any]
    status: int
    message: str
    source_kind: str
    cache_hit: bool
    request_hash: str
    response_hash: str
    latency_ms: int
    trace_id: str
    expires_at: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == 0


class BaiduService:
    def __init__(self, settings: Settings, *, adapter: Optional[BaiduAdapter] = None,
                 cache: Optional[ApiCache] = None, ledger: Optional[ProductLedger] = None,
                 rate_limiter: Optional[AdaptiveRateLimiter] = None) -> None:
        self.settings = settings
        if adapter is not None:
            self.adapter = adapter
            default_qps = 0.0
        else:
            self.adapter = BaiduAdapter(settings.request_timeout_s,
                                        app_key=settings.baidu_ak, sign_key=settings.baidu_sk)
            try:
                default_qps = float(os.environ.get("BAIDU_MAX_QPS", "10.0"))
            except ValueError as exc:
                raise ConfigError("BAIDU_MAX_QPS 必须是正数") from exc
            if not math.isfinite(default_qps) or default_qps <= 0:
                raise ConfigError("BAIDU_MAX_QPS 必须是有限正数")
        self.cache = cache or ApiCache(settings.cache_db)
        self.ledger = ledger or ProductLedger(settings.ledger_db)
        if not math.isfinite(default_qps) or default_qps < 0:
            raise ValueError("BAIDU_MAX_QPS must be finite and nonnegative")
        self.rate_limiter = rate_limiter or AdaptiveRateLimiter(base_qps=default_qps, burst=1)
        # 官方批量算路的并发按路线条数计费，单起点×16终点不是1次并发。
        self._interface_limits = {}
        self._matrix_batch_size = 50
        self._matrix_parallel = adapter is None
        if adapter is None:
            try:
                matrix_pps = int(os.environ.get('BAIDU_MATRIX_PAIRS_PER_SECOND', '3'))
                other_qps = int(os.environ.get('BAIDU_INTERFACE_QPS', '3'))
                if not 1 <= matrix_pps <= 10000 or not 1 <= other_qps <= 10000:
                    raise ValueError()
                matrix_capacity = int(os.environ.get('BAIDU_MATRIX_ROUTES_PER_WINDOW', str(matrix_pps)))
                matrix_window_s = float(os.environ.get('BAIDU_MATRIX_WINDOW_SECONDS', '1.05'))
                if not 1 <= matrix_capacity <= 10000 or not math.isfinite(matrix_window_s) or not 0 < matrix_window_s <= 60:
                    raise ValueError()
            except ValueError as exc:
                raise ConfigError('百度接口额度必须为1至10000的整数，时间窗必须为0至60秒的有限正数') from exc
            self._matrix_batch_size = min(50, matrix_capacity)
            self._interface_limits = {name: WindowRateLimiter(
                matrix_capacity if name == 'matrix_walking' else other_qps,
                window_s=matrix_window_s if name == 'matrix_walking' else 1.05)
                for name in ('matrix_walking', 'place_search', 'place_detail', 'geocode', 'reverse_geocode', 'direction_walking')}
        self._slots = threading.BoundedSemaphore(4)
        self._cooldowns: Dict[str, Tuple[float, ServiceError]] = {}
        self._cooldown_lock = threading.Lock()
        self._rate_strikes: Dict[str, int] = {}
        self._singleflight = Singleflight()

    # ---------- 统一缓存/账本/live 出口 ----------

    def _resolve(self, *, trace_id: str, stage: str, interface: str,
                 interface_version: str, params: Dict[str, Any],
                 invoke: Callable[[], Any], pairs: int = 1,
                 ttl_s: float = _LIVE_TTL_S) -> GatewayResult:
        key = request_hash(interface, interface_version, "BD09", params)

        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            self.ledger.record(
                trace_id=trace_id, stage=stage, interface=interface,
                request_hash=key, cache_hit=True, status=cached.status,
                requests=1, pairs=pairs, latency_ms=0,
                message=cached.message, response_hash=cached.response_hash,
            )
            if cached.status != 0:
                raise self._error_from_status(cached.status, cached.message)
            return GatewayResult(interface, cached.body, cached.status, cached.message,
                                 "api-cache", True, key, cached.response_hash,
                                 0, trace_id, cached.expires_at)

        def check_cooldown() -> None:
            with self._cooldown_lock:
                blocked = self._cooldowns.get(interface)
                if blocked and blocked[0] > time.monotonic():
                    retry_after = max(1, math.ceil(blocked[0] - time.monotonic()))
                    exc = blocked[1]
                    raise ServiceError(exc.code, exc.message, http_status=exc.http_status,
                                       details={**(exc.details or {}), "cooldown": True},
                                       retryable=exc.retryable, retry_after=retry_after)
                self._cooldowns.pop(interface, None)

        def _call_upstream() -> Tuple[int, Dict[str, Any], str, int, str, Optional[str], int]:
            # 入口查缓存后，另一个leader可能刚完成；再次检查避免注册竞态导致重复收费。
            fresh = self.cache.get(key) if self.cache else None
            if fresh is not None and fresh.status == 0:
                return fresh.status, fresh.body, fresh.message, 0, fresh.response_hash, fresh.expires_at, 0
            check_cooldown()
            if not self._slots.acquire(timeout=2):
                raise ServiceError("SERVICE_BUSY", "查询较多，请稍后重试", http_status=503,
                                   retryable=True, retry_after=2)
            try:
                # 每一次重试重新经过匀速限制，网络重试不在适配器内绕过限流。
                raw: Any = None
                for attempt in range(3):
                    check_cooldown()
                    try:
                        self.rate_limiter.acquire(1.0)
                        quota = self._interface_limits.get(interface)
                        if quota is not None:
                            quota.acquire(pairs if interface == 'matrix_walking' else 1)
                    except TimeoutError as exc:
                        raise ServiceError("SERVICE_BUSY", "查询正在排队，请稍后重试", http_status=503,
                                           retryable=True, retry_after=2) from exc
                    # 在排队期间其他请求可能已触发冷却，放行前必须再检查。
                    check_cooldown()
                    raw = invoke()
                    st = int(getattr(raw, "status", -1))
                    http_status = getattr(raw, "http_status", None)
                    if http_status in (401, 403):
                        st = 211
                    elif http_status == 429:
                        st = 401
                    elif http_status and http_status >= 500:
                        st = -5
                    elif getattr(raw, "failure_kind", None) == "timeout":
                        st = -3
                    raw.status = st
                    if st == 401:
                        # 401按实验建议冷却15/30/60秒；不占HTTP线程等待，也不立即轰炸重试。
                        self.rate_limiter.on_rate_limited(attempt, base_Wait_s=0)
                        if quota is not None:
                            quota.on_rate_limited()
                        break
                    if st == 0 or st not in (1, 401, -1, -3, -5) or attempt == 2:
                        break
                    self.ledger.record(trace_id=trace_id, stage=stage, interface=interface,
                        request_hash=key, cache_hit=False, status=st,
                        requests=int(getattr(raw, "attempts", 1)), pairs=pairs,
                        latency_ms=int(getattr(raw, "latency_ms", 0)),
                        message=self._error_from_status(st, "").message, response_hash="")
                    if st == 401:
                        self.rate_limiter.on_rate_limited(attempt)
                    else:
                        time.sleep(0.3 * 2 ** attempt)
                st = int(getattr(raw, "status", -1))
                if st != 0:
                    err = self._error_from_status(st, "")
                    if st in (4, 302):
                        now = datetime.now(timezone(timedelta(hours=8)))
                        seconds = int(((now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0) - now).total_seconds())
                    elif st == 401:
                        with self._cooldown_lock:
                            strikes = self._rate_strikes.get(interface, 0) + 1
                            self._rate_strikes[interface] = min(strikes, 3)
                        seconds = min(60, 15 * 2 ** min(strikes - 1, 2))
                    elif err.code == "UPSTREAM_AUTH":
                        seconds = 300
                    else:
                        seconds = 5 if err.retryable else 0
                    if seconds:
                        with self._cooldown_lock:
                            self._cooldowns[interface] = (time.monotonic() + seconds, err)
            finally:
                self._slots.release()
            st = int(getattr(raw, "status", -1))
            if st == 0:
                self.rate_limiter.on_success()
                quota = self._interface_limits.get(interface)
                if quota is not None:
                    quota.on_success()
                with self._cooldown_lock:
                    self._rate_strikes.pop(interface, None)
            bd = dict(getattr(raw, "data", {}) or {})
            msg = "" if st == 0 else self._error_from_status(st, "").message
            lat = int(getattr(raw, "latency_ms", 0) or 0)
            rh = response_hash(bd)
            exp = None
            if st == 0 and self.cache:
                saved = self.cache.put(
                    interface=interface, interface_version=interface_version, crs="BD09",
                    params=params, body=bd, status=st, message=msg,
                    latency_ms=lat, source_kind="live-api", ttl_s=ttl_s,
                )
                exp = saved.expires_at
            return st, bd, msg, lat, rh, exp, int(getattr(raw, "attempts", 1))

        try:
            (status, body, message, latency_ms, r_hash, expires_at, attempts), shared = self._singleflight.do(key, _call_upstream)
        except TimeoutError as exc:
            raise ServiceError("SERVICE_BUSY", "查询等待超时，请稍后重试", http_status=503,
                               retryable=True, retry_after=2) from exc
        if (shared or attempts == 0) and status == 0:
            self.ledger.record(
                trace_id=trace_id, stage=stage, interface=interface,
                request_hash=key, cache_hit=True, status=status,
                requests=1, pairs=pairs, latency_ms=0,
                message="SINGLEFLIGHT_COALESCED", response_hash=r_hash,
            )
            return GatewayResult(interface, body, status, message, "api-cache", True,
                                 key, r_hash, 0, trace_id, expires_at)

        self.ledger.record(
            trace_id=trace_id, stage=stage, interface=interface, request_hash=key,
            cache_hit=False, status=status, requests=0 if shared else attempts,
            pairs=0 if shared else pairs * attempts,
            latency_ms=latency_ms, message=message, response_hash=r_hash,
        )
        if status != 0:
            # 过期数据不能参加覆盖/规划；有效缓存已在入口优先复用。
            err = self._error_from_status(status, message)
            with self._cooldown_lock:
                blocked = self._cooldowns.get(interface)
            if blocked:
                err.retry_after = max(1, math.ceil(blocked[0] - time.monotonic()))
            raise err
        return GatewayResult(interface, body, status, message, "live-api", False,
                             key, r_hash, latency_ms, trace_id, expires_at)

    @staticmethod
    def _error_from_status(status: int, message: str) -> ServiceError:
        details = {"upstreamStatus": status}
        if status in (4, 302):
            return ServiceError("QUOTA_EXCEEDED", "地图查询额度暂时用尽，已有有效结果仍可使用", http_status=429, details=details)
        if status == 401:
            return ServiceError("RATE_LIMITED", "地图查询较多，请稍后重试", http_status=429, details=details, retryable=True, retry_after=5)
        if status == 2001:
            return ServiceError("NO_ROUTE", "暂未查到可用步行路线，请重新选择地点", http_status=404, details=details)
        if status in (3, 5, 101, 102, 200, 201, 202, 203, 210, 211, 220, 230, 240, 250, 251):
            return ServiceError("UPSTREAM_AUTH", "地图服务授权或配置异常，请联系维护者", http_status=503, details=details)
        if status in (2, 10, 11):
            return ServiceError("UPSTREAM_ARGUMENT", "地点查询参数无效，请重新选择地点", http_status=422, details=details)
        code, text, http = {
            -1: ("UPSTREAM_NETWORK", "地图服务连接失败，请稍后重试", 502),
            -3: ("UPSTREAM_TIMEOUT", "地图查询超时，请稍后重试", 504),
            -5: ("UPSTREAM_UNAVAILABLE", "地图服务暂时不可用，请稍后重试", 502),
            1: ("UPSTREAM_UNAVAILABLE", "地图服务暂时不可用，请稍后重试", 502),
            -2: ("UPSTREAM_RESPONSE", "地图服务返回不完整，请稍后重试", 502),
        }.get(status, ("BAIDU_API_ERROR", "地图查询未完成，请稍后重试", 502))
        return ServiceError(code, text, http_status=http, details=details,
                            retryable=status in (1, -1, -3, -5), retry_after=5 if status in (1, -1, -3, -5) else None)

    # ---------- 领域方法 ----------

    def resolve_location(self, coord: Coord) -> Tuple[PlaceRef, str]:
        point, _ = to_baidu_bd09(coord)
        trace = new_trace_id()
        resolved = self._resolve(
            trace_id=trace, stage="A1", interface="reverse_geocode", interface_version="v3",
            params={"lng": point.lng, "lat": point.lat, "crs": "BD09"}, pairs=1,
            invoke=lambda: self.adapter.reverse_geocode((point.lat, point.lng), experiment_id=trace),
        )
        result = resolved.body.get("result") or {}
        address = str(result.get("formatted_address") or "").strip()
        if not address:
            raise ServiceError("NO_RESULT", "未查到该位置的地址，可手动填写地点名称", http_status=404)
        # 地址属于查询坐标，不能用附近POI的位置替换用户精确选点。
        return PlaceRef(name=address, address=address, coord=point, source=resolved.source_kind), trace

    def search_locations(self, query: str, city: Optional[str] = None,
                         trace_id: Optional[str] = None) -> Tuple[List[PlaceRef], str]:
        trace = trace_id or new_trace_id()
        q = query.strip()
        if not q:
            raise ServiceError("VALIDATION_ERROR", "q 不能为空")
        params = {"query": q, "city": city or "", "scope": 2,
                  "pageSize": 10, "pageNum": 0}
        result = self._resolve(
            trace_id=trace, stage="A1", interface="place_search",
            interface_version="v2", params=params, pairs=1,
            invoke=lambda: self.adapter.place_search(
                q, region=city, page_size=10, page_num=0, experiment_id=trace),
        )
        candidates = [c for c in (self._place_from_item(it, result.source_kind)
                                  for it in (result.body.get("results") or []))
                      if c is not None]
        if candidates:
            return candidates, trace

        # 地点检索无候选时,用地理编码给出一个无 UID 地址点。
        geo_params = {"address": q, "city": city or ""}
        geo = self._resolve(
            trace_id=trace, stage="A1", interface="geocode", interface_version="v3",
            params=geo_params, pairs=1,
            invoke=lambda: self.adapter.geocode(q, city=city, experiment_id=trace),
        )
        loc = (geo.body.get("result") or {}).get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            raise ServiceError("NO_RESULT", f"未找到地点: {q}", http_status=404)
        return [PlaceRef(
            name=q,
            address=q,
            coord=Coord(lng=float(loc["lng"]), lat=float(loc["lat"]), crs="BD09"),
            source=geo.source_kind,
        )], trace

    @staticmethod
    def _place_from_item(item: Dict[str, Any], source_kind: str) -> Optional[PlaceRef]:
        if not isinstance(item, dict):
            return None
        loc = item.get("location") or {}
        if not isinstance(loc, dict):
            return None
        if loc.get("lat") is None or loc.get("lng") is None:
            return None
        try:
            coord = Coord(lng=float(loc['lng']), lat=float(loc['lat']), crs='BD09')
        except (ValueError, TypeError):
            return None
        detail_info = item.get("detail_info") if isinstance(item.get("detail_info"), dict) else {}
        navi = detail_info.get("navi_location") or {}
        navi_coord = None
        if isinstance(navi, dict) and navi.get("lat") is not None and navi.get("lng") is not None:
            try:
                navi_coord = Coord(lng=float(navi["lng"]), lat=float(navi["lat"]), crs="BD09")
            except (ValueError, TypeError):
                pass  # 导航引导点不合法时只使用已验证的位置，不编造新坐标。
        return PlaceRef(
            uid=item.get("uid"),
            name=item.get("name") or "",
            address=item.get("address"),
            tags=list(dict.fromkeys(value for value in (item.get("tag"), detail_info.get("tag"))
                                    if isinstance(value, str) and value.strip())),
            coord=coord,
            naviCoord=navi_coord,
            source=source_kind,
        )

    @staticmethod
    def _normalize_hours(detail_info: Dict[str, Any]) -> tuple:
        """F43：百度真实营业时间归一化。

        真实字段是 detail_info.regular_open_hour.periods（open/close 各含 day/hour/minute），
        兼容旧 shop_hours_structured。返回 (shop_hours, structured_hours)：
        - periods 按 day 分组，同 day 多段全部保留（含跨午夜 close.day != open.day）；
        - close 缺失表示未知，不推断全天营业；
        - day 缺失/非法则该段降级（整店未知时 structuredHours=None，由前端标 unknown）。
        """
        shop_hours = detail_info.get("shop_hours") or None
        raw_periods = ((detail_info.get("regular_open_hour") or {}).get("periods")
                       or detail_info.get("shop_hours_structured"))
        if not isinstance(raw_periods, list) or not raw_periods:
            return shop_hours, None
        structured: list = []
        for period in raw_periods:
            if not isinstance(period, dict):
                continue
            open_info = period.get("open") or {}
            close_info = period.get("close") or {}
            try:
                open_day = int(open_info.get("day", -1))
                open_hour = int(open_info.get("hour", -1))
                open_minute = int(open_info.get("minute", 0))
                open_sec = open_hour * 3600 + open_minute
            except (TypeError, ValueError):
                continue
            if not 0 <= open_day <= 6 or not 0 <= open_hour <= 23 or not 0 <= open_minute <= 59:
                continue
            if close_info:
                try:
                    close_day = int(close_info.get("day", open_day))
                    close_hour = int(close_info.get("hour", -1))
                    close_minute = int(close_info.get("minute", 0))
                    close_sec = close_hour * 3600 + close_minute
                except (TypeError, ValueError):
                    continue
                if not 0 <= close_day <= 6 or not 0 <= close_hour <= 23 or not 0 <= close_minute <= 59:
                    continue
            else:
                continue
            structured.append({"day": open_day, "opensSeconds": open_sec,
                               "closeDay": close_day, "closesSeconds": close_sec})
        if not structured:
            return shop_hours, None
        return shop_hours, structured

    @staticmethod
    def _place_from_detail(item: Dict[str, Any], source_kind: str) -> Optional[PlaceRef]:
        loc = item.get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            return None
        detail_info = item.get("detail_info") or {}
        navi = detail_info.get("navi_location") or {}
        navi_coord = None
        if navi.get("lat") is not None and navi.get("lng") is not None:
            navi_coord = Coord(lng=float(navi["lng"]), lat=float(navi["lat"]), crs="BD09")
        shop_hours, structured_hours = BaiduService._normalize_hours(detail_info)
        return PlaceRef(
            uid=item.get("uid"),
            name=item.get("name") or "",
            address=item.get("address"),
            coord=Coord(lng=float(loc["lng"]), lat=float(loc["lat"]), crs="BD09"),
            tags=list(dict.fromkeys(value for value in (item.get("tag"), detail_info.get("tag"))
                                    if isinstance(value, str) and value.strip())),
            naviCoord=navi_coord,
            source=source_kind,
            shopHours=shop_hours,
            structuredHours=structured_hours,
            status=detail_info.get("status") or None,
        )

    def place_detail(self, uid: str, trace_id: Optional[str] = None) -> Tuple[PlaceRef, str]:
        trace = trace_id or new_trace_id()
        if not uid:
            raise ServiceError("VALIDATION_ERROR", "uid 不能为空")
        params = {"uid": uid, "scope": 2}
        result = self._resolve(
            trace_id=trace, stage="A2", interface="place_detail",
            interface_version="v3", params=params, pairs=1,
            invoke=lambda: self.adapter.place_detail(uid, experiment_id=trace),
        )
        body = result.body
        item = body.get("result")
        if not isinstance(item, dict):
            results = body.get("results") or []
            item = results[0] if results and isinstance(results[0], dict) else None
        if item is None:
            raise ServiceError("NO_RESULT", f"POI 详情为空: {uid}", http_status=404)
        place = self._place_from_detail(item, result.source_kind)
        if place is None:
            raise ServiceError("NO_RESULT", f"POI 详情缺少坐标: {uid}", http_status=404)
        return place, trace

    def corridor_pois(self, route_geometry: List[Coord], query_terms: List[str], *,
                      category: str = "", corridor_buffer_m: float = 1500.0,
                      window_spacing_m: float = 0.0, window_radius_m: float = 1000.0,
                      max_pages_per_window: int = 3, max_unique: int = 100,
                      detail_limit: int = 0,
                      trace_id: Optional[str] = None) -> Dict[str, Any]:
        trace = trace_id or new_trace_id()
        # F61：路线几何先转 BD09；任一失败直接 422。
        route_geometry = [to_baidu_bd09(c)[0] for c in route_geometry]
        pts = [(c.lng, c.lat) for c in route_geometry]
        if len(pts) < 2:
            raise ServiceError("VALIDATION_ERROR", "routeGeometry 至少需要两个点")
        terms = [t.strip() for t in query_terms if t.strip()]
        if not terms:
            raise ServiceError("VALIDATION_ERROR", "queryTerms 不能为空")
        if window_radius_m <= 0 or corridor_buffer_m <= 0:
            raise ServiceError("VALIDATION_ERROR", "窗口半径和走廊缓冲必须大于 0")

        centers = sample_centers(pts, spacing_m=window_spacing_m or window_radius_m,
                                 radius_m=window_radius_m)
        unique: Dict[str, Dict[str, Any]] = {}
        source_by_key: Dict[str, str] = {}
        raw_count = 0
        pages = 0
        cache_hits = 0
        expirations: List[Optional[str]] = []
        truncation_reason: Optional[str] = None

        warnings: List[str] = []
        degraded_stop = False
        for center in centers:
            if degraded_stop:
                break
            for term in terms:
                if degraded_stop:
                    break
                items: List[Dict[str, Any]] = []
                for page in range(max_pages_per_window):
                    params = {
                        "query": term,
                        "location": [center[1], center[0]],
                        "radius": window_radius_m,
                        "scope": 2,
                        "pageSize": 20,
                        "pageNum": page,
                    }
                    try:
                        result = self._resolve(
                            trace_id=trace, stage="A2", interface="place_search",
                            interface_version="v2", params=params, pairs=1,
                            invoke=lambda term=term, center=center, page=page: self.adapter.place_search(
                                term, location=(center[1], center[0]),
                                radius=int(window_radius_m), page_num=page,
                                page_size=20, experiment_id=trace,
                            ),
                        )
                    except ServiceError as exc:
                        if pages > 0 and exc.code in {"QUOTA_EXCEEDED", "RATE_LIMITED", "UPSTREAM_ERROR", "UPSTREAM_NETWORK", "UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE", "SERVICE_BUSY"}:
                            truncation_reason = truncation_reason or f"degraded:{exc.code}"
                            warnings.append(f"POI检索降级({exc.code})：已保留前 {pages} 页结果")
                            degraded_stop = True
                            break
                        raise
                    items = result.body.get("results") or []
                    cache_hits += int(result.cache_hit)
                    expirations.append(result.expires_at)
                    raw_count += len(items)
                    pages += 1
                    for item in items:
                        if self._place_from_item(item, result.source_kind) is None:
                            truncation_reason = truncation_reason or 'invalid_coordinates'
                            continue
                        loc = item.get("location") or {}
                        key = item.get("uid") or (
                            f"{item.get('name')}|{loc.get('lat')}|{loc.get('lng')}|{item.get('address')}"
                        )
                        if key not in unique:
                            unique[key] = item
                            source_by_key[key] = result.source_kind
                    if not items:
                        break
                    if len(items) < 20:
                        break
                    if page == max_pages_per_window - 1:
                        truncation_reason = f"page_budget:{term}"

        candidates: List[Dict[str, Any]] = []
        detail_done = 0
        for key, item in unique.items():
            place = self._place_from_item(item, source_by_key[key])
            if place is None:
                continue
            distance = point_to_polyline_m((place.coord.lng, place.coord.lat), pts)
            if distance > corridor_buffer_m:
                continue
            if detail_limit and detail_done < detail_limit and place.uid:
                try:
                    place, _ = self.place_detail(place.uid, trace_id=trace)
                    detail_done += 1
                except ServiceError:
                    warnings.append(f"detail 失败: {place.uid}")
            candidates.append({
                "place": place.model_dump(by_alias=True),
                "distanceToRouteM": round(distance, 1),
            })

        candidates.sort(key=lambda row: row["distanceToRouteM"])
        truncated = bool(truncation_reason) or len(candidates) > max_unique
        if len(candidates) > max_unique:
            candidates = candidates[:max_unique]
            truncation_reason = truncation_reason or "max_unique"

        return {
            "traceId": trace,
            "mode": "live",
            "sourceKind": "derived",
            "cacheHit": pages > 0 and cache_hits == pages,
            "expiresAt": min(expirations) if expirations and all(expirations) and not detail_limit else None,
            "retrieval": {
                "queryTerms": terms,
                "category": category,
                "windows": len(centers),
                "pages": pages,
                "rawCount": raw_count,
                "uniqueCount": len(unique),
                "truncated": truncated,
                "truncationReason": truncation_reason,
                "sourceKind": "derived",
            },
            "pois": candidates,
            "warnings": warnings,
        }

    def corridor_evidence(self, poi: Coord, route_geometry: List[Coord], *,
                          baseline_duration_seconds: float,
                          threshold_seconds: float,
                          sample_m: float = 200.0,
                          max_samples: int = 12,
                          trace_id: Optional[str] = None) -> Dict[str, Any]:
        """路线采样点 ↔ POI 双向测时证据;出发圈与返回圈分开计算。"""
        trace = trace_id or new_trace_id()
        # F61：POI 与路线几何先转 BD09（travel_matrix 内部会再转，幂等）。
        poi, _ = to_baidu_bd09(poi)
        route_geometry = [to_baidu_bd09(c)[0] for c in route_geometry]
        samples = sample_geometry(
            [coord.model_dump() for coord in route_geometry],
            total_duration_s=baseline_duration_seconds,
            sample_m=sample_m,
            source_kind="derived",
        )
        if not samples:
            raise ServiceError("VALIDATION_ERROR", "routeGeometry 无法抽样")
        if len(samples) > max_samples:
            indexes = sorted({round(i * (len(samples) - 1) / (max_samples - 1))
                              for i in range(max_samples)})
            samples = [samples[index] for index in indexes]

        sample_coords = [Coord(lng=item.lng, lat=item.lat, crs="BD09") for item in samples]
        inbound_matrix = self.travel_matrix(sample_coords, [poi], trace_id=trace)
        outbound_matrix = self.travel_matrix([poi], sample_coords, trace_id=trace)
        inbound = [
            next((cell["durationSeconds"] for cell in inbound_matrix["cells"]
                  if cell["fromIndex"] == index and cell["toIndex"] == 0), None)
            for index in range(len(samples))
        ]
        outbound = [
            next((cell["durationSeconds"] for cell in outbound_matrix["cells"]
                  if cell["fromIndex"] == 0 and cell["toIndex"] == index), None)
            for index in range(len(samples))
        ]
        evidence = compute_corridor_evidence(
            threshold_seconds=threshold_seconds,
            inbound_times=inbound,
            outbound_times=outbound,
        )
        best = keep_route_detour(
            prefix_seconds=[item.prefix_seconds for item in samples],
            route_to_poi=inbound,
            poi_to_route=outbound,
            baseline_seconds=baseline_duration_seconds,
        )
        return {
            "traceId": trace,
            "mode": "live",
            "sourceKind": "derived",
            "thresholdSeconds": threshold_seconds,
            "pairsUsed": len(samples) * 2,
            "samples": [
                {
                    "index": index,
                    "coord": sample_coords[index].model_dump(),
                    "distanceFromStartM": round(item.distance_m, 1),
                    "prefixSeconds": round(item.prefix_seconds, 1),
                    "inboundSeconds": inbound[index],
                    "outboundSeconds": outbound[index],
                    "inboundReachable": index in evidence.inbound_reachable_indices,
                    "outboundReachable": index in evidence.outbound_reachable_indices,
                }
                for index, item in enumerate(samples)
            ],
            "evidence": evidence.as_dict(),
            "bestAccess": best.best.__dict__ if best.best else None,
            "warnings": [],
        }

    def walking_route(self, origin: Coord, destination: Coord,
                      trace_id: Optional[str] = None) -> Dict[str, Any]:
        trace = trace_id or new_trace_id()
        # F61：唯一出口转换后再发请求；响应保留原始坐标与转换追踪。
        origin_bd, origin_from = to_baidu_bd09(origin)
        dest_bd, dest_from = to_baidu_bd09(destination)
        o = (origin_bd.lat, origin_bd.lng)
        d = (dest_bd.lat, dest_bd.lng)
        params = {"origin": list(o), "destination": list(d), "mode": "walking"}
        result = self._resolve(
            trace_id=trace, stage="A1", interface="direction_walking",
            interface_version="v2", params=params, pairs=1,
            invoke=lambda: self.adapter.walking(o, d, experiment_id=trace),
        )
        routes = (result.body.get("result") or {}).get("routes") or []
        if not routes:
            raise ServiceError("NO_ROUTE", "百度未返回步行路线", http_status=404)
        summary = route_leg_summary(routes[0])
        if summary["durationSeconds"] is None or summary["distanceM"] is None:
            raise ServiceError("NO_ROUTE", "百度路线缺少时长或距离", http_status=404)
        warnings = []
        if origin_from or dest_from:
            warnings.append(
                f"坐标已转换: origin {origin_from or 'BD09'}->BD09, "
                f"destination {dest_from or 'BD09'}->BD09")
        return {
            "traceId": trace,
            "mode": "live",
            "sourceKind": result.source_kind,
            "cacheHit": result.cache_hit,
            "route": summary,
            "warnings": warnings,
        }

    def peek_matrix(self, origins: List[Coord], destinations: List[Coord], *, allow_partial: bool = False) -> Optional[Dict[str, Any]]:
        """F49：只读 API 缓存，不触发 live 调用、不写账本。命中返回聚合结果，缺失返回 None。"""
        from ..storage.api_cache import request_hash as _request_hash  # noqa: E402
        if self.cache is None or not origins or not destinations:
            return None
        # F61：peek 同样走转换后的 BD09 查缓存。
        try:
            origins = [to_baidu_bd09(c)[0] for c in origins]
            destinations = [to_baidu_bd09(c)[0] for c in destinations]
        except ServiceError:
            return None
        n_dest = len(destinations)
        indexed = self.cache.matrix_cells([[c.lat, c.lng] for c in origins],
                                         [[c.lat, c.lng] for c in destinations])
        if len(indexed) == len(origins) * n_dest or (allow_partial and indexed):
            expirations = [cell.get('expiresAt') for cell in indexed.values()]
            return {'cells': [self._matrix_cell(i, j, indexed.get((i, j), {}).get('item'), 'api-cache')
                              for i in range(len(origins)) for j in range(n_dest)],
                    'expiresAt': min(expirations) if expirations and all(expirations) else None,
                    'responseHashes': sorted({cell['responseHash'] for cell in indexed.values()})}
        rows_per_batch = max(1, 50 // max(1, n_dest))
        bodies: list = []
        hashes: list = []
        kinds: list = []
        expirations: list = []
        for row_start in range(0, len(origins), rows_per_batch):
            o_slice = origins[row_start:row_start + rows_per_batch]
            params = {"origins": [[c.lat, c.lng] for c in o_slice],
                      "destinations": [[c.lat, c.lng] for c in destinations],
                      "mode": "walking"}
            key = _request_hash("matrix_walking", "v2", "BD09", params)
            cached = self.cache.get(key)
            if cached is None or cached.status != 0:
                return None
            bodies.append(cached.body)
            hashes.append(cached.response_hash)
            kinds.append("api-cache")
            expirations.append(cached.expires_at)
        cells: list = []
        for batch_index, body in enumerate(bodies):
            raw_items = body.get('result') if isinstance(body.get('result'), list) else []
            expected = min(rows_per_batch, len(origins) - batch_index * rows_per_batch) * n_dest
            for index in range(expected):
                item = raw_items[index] if index < len(raw_items) else None
                cells.append(self._matrix_cell(batch_index * rows_per_batch + index // n_dest,
                                               index % n_dest, item, kinds[batch_index]))
        return {"cells": cells, "responseHashes": hashes,
                "expiresAt": min(expirations) if expirations and all(expirations) else None}

    def travel_matrix(self, origins: List[Coord], destinations: List[Coord],
                      trace_id: Optional[str] = None, *, stage: str = "A3") -> Dict[str, Any]:
        """有方向 OD 矩阵；按 ≤50 对拆分逐批请求，缺失 cell 补 no_route/error。

        每批走统一 _resolve（缓存/账本按批记录）；返回完整
        len(origins)×len(destinations) 网格，缺项 status=error。
        stage 只决定账本行归属：plan-OD 路径默认 'A3'，等时圈
        measure_batch 显式传 'isochrone'，便于按 stage 拆分成本。
        """
        trace = trace_id or new_trace_id()
        if not origins or not destinations:
            raise ServiceError("VALIDATION_ERROR", "origins/destinations 不能为空")
        # F61：整批先转 BD09；任一失败直接 422，不写错误缓存。
        origins_bd = [to_baidu_bd09(c)[0] for c in origins]
        destinations_bd = [to_baidu_bd09(c)[0] for c in destinations]
        converted = any(
            to_baidu_bd09(c)[1] is not None for c in (*origins, *destinations))
        n_orig, n_dest = len(origins_bd), len(destinations_bd)
        cells: Dict[tuple, Dict[str, Any]] = {}
        warnings: List[str] = []
        cache_hits = 0
        batches = 0
        expirations: List[Optional[str]] = []
        response_hashes: List[str] = []
        batch_errors = []
        first_error = None
        jobs = []
        if converted:
            warnings.append("坐标已转换: 部分输入非 BD09，已统一转 BD09 再请求")
        # 先把 destination 列分到每批最多 50 个，再按该列块大小切 origins 行；
        # 两个维度都可拆，任何上游请求的 OD pair 数都不会超过 50。
        batch_size = self._matrix_batch_size
        for dest_start in range(0, n_dest, batch_size):
            dest_end = min(n_dest, dest_start + batch_size)
            d_slice = destinations_bd[dest_start:dest_end]
            d_points = [(c.lat, c.lng) for c in d_slice]
            value_d = [[c.lat, c.lng] for c in d_slice]
            rows_per_batch = max(1, batch_size // len(d_slice))
            for row_start in range(0, n_orig, rows_per_batch):
                row_end = min(n_orig, row_start + rows_per_batch)
                o_slice = origins_bd[row_start:row_end]
                o_points = [(c.lat, c.lng) for c in o_slice]
                values = [[c.lat, c.lng] for c in o_slice]
                params = {"origins": values, "destinations": value_d, "mode": "walking"}
                indexed = self.cache.matrix_cells(values, value_d) if self.cache else {}
                groups: Dict[str, list] = {}
                for (i, j), cached in indexed.items():
                    cells[(row_start + i, dest_start + j)] = self._matrix_cell(
                        row_start + i, dest_start + j, cached['item'], 'api-cache')
                    groups.setdefault(cached['requestHash'], []).append(cached)
                for source_key, group in groups.items():
                    expirations.append(group[0].get('expiresAt'))
                    self.ledger.record(trace_id=trace, stage=stage, interface='matrix_walking',
                        request_hash=source_key, cache_hit=True, status=0, requests=1,
                        pairs=len(group), latency_ms=0, response_hash=group[0]['responseHash'])
                    response_hashes.append(group[0]['responseHash'])
                    batches += 1
                    cache_hits += 1
                if indexed:
                    # 仅请求缺失 OD；每行合并缺失列，保证请求内不夹带已经命中的对。
                    chunks = [([i], [j for j in range(len(d_slice)) if (i, j) not in indexed])
                              for i in range(len(o_slice))]
                    chunks = [(rows, columns) for rows, columns in chunks if columns]
                else:
                    chunks = [(list(range(len(o_slice))), list(range(len(d_slice))))]
                for rows, columns in chunks:
                    starts = [o_points[i] for i in rows]
                    ends = [d_points[j] for j in columns]
                    params = {'origins': [values[i] for i in rows],
                              'destinations': [value_d[j] for j in columns], 'mode': 'walking'}
                    jobs.append((rows, columns, row_start, dest_start, starts, ends, params))

        def resolve_job(job):
            rows, columns, row_start, dest_start, starts, ends, params = job
            try:
                return self._resolve(trace_id=trace, stage=stage, interface='matrix_walking',
                    interface_version='v2', params=params, pairs=len(starts) * len(ends),
                    invoke=lambda: self.adapter.routematrix(starts, ends, experiment_id=trace))
            except ServiceError as exc:
                return exc

        # 同轮各批互不依赖：最多2个请求并行，仍共享全局4槽及路线数时间窗。
        # 测试适配器默认顺序执行；不会把后续二分轮次提前发送。
        pool = ThreadPoolExecutor(max_workers=2) if self._matrix_parallel and len(jobs) > 1 else None
        try:
            responses = pool.map(resolve_job, jobs) if pool else map(resolve_job, jobs)
            for job, result in zip(jobs, responses):
                rows, columns, row_start, dest_start, _, _, _ = job
                if isinstance(result, ServiceError):
                    if first_error is None:
                        first_error = result
                    if result.code not in {'QUOTA_EXCEEDED', 'RATE_LIMITED', 'UPSTREAM_ERROR', 'UPSTREAM_NETWORK', 'UPSTREAM_TIMEOUT', 'UPSTREAM_UNAVAILABLE', 'SERVICE_BUSY'}:
                        raise result
                    batch_errors.append({'code': result.code, 'retryAfterSeconds': result.retry_after})
                    warnings.append(f'matrix batch 降级({result.code})：未完成批次记为 error')
                    continue
                batches += 1
                cache_hits += int(result.cache_hit)
                expirations.append(result.expires_at)
                response_hashes.append(result.response_hash)
                raw_items = result.body.get('result') if isinstance(result.body.get('result'), list) else []
                expected = len(rows) * len(columns)
                if len(raw_items) != expected:
                    warnings.append(f'matrix batch 返回 {len(raw_items)} 项，期望 {expected} 项，缺失补 error')
                for index in range(expected):
                    oi, dj = divmod(index, len(columns))
                    i, j = row_start + rows[oi], dest_start + columns[dj]
                    item = raw_items[index] if index < len(raw_items) else None
                    cells[(i, j)] = self._matrix_cell(i, j, item, result.source_kind)
        finally:
            if pool:
                pool.shutdown(wait=True)
        if not cells and first_error is not None:
            raise first_error
        full_cells = []
        for origin_index in range(n_orig):
            for dest_index in range(n_dest):
                cell = cells.get((origin_index, dest_index))
                if cell is None:
                    cell = {
                        "fromIndex": origin_index,
                        "toIndex": dest_index,
                        "durationSeconds": None,
                        "distanceM": None,
                        "status": "error",
                        "sourceKind": "derived",
                    }
                    warnings.append(f"matrix cell {origin_index}->{dest_index} 缺失，记 error")
                full_cells.append(cell)
        # F65：多批次来源按 cell 聚合；混合命中时顶层标混合，不冒充单一来源。
        kinds = {cell["sourceKind"] for cell in full_cells} - {"derived"}
        top_kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
        if top_kind == "mixed":
            warnings.append("来源混合：部分批次命中 API 缓存，部分为实时请求；各 cell 来源见 sourceKind")
        return {
            "traceId": trace,
            "mode": "live",
            "sourceKind": top_kind,
            "cacheHit": cache_hits == batches,
            "expiresAt": min(expirations) if expirations and all(expirations) else None,
            "cells": full_cells,
            "warnings": warnings,
            "responseHashes": sorted(set(response_hashes)),
            "errors": batch_errors,
        }

    @staticmethod
    def _matrix_cell(i: int, j: int, item: Any, kind: str) -> dict:
        import math
        duration_object = item.get('duration') if isinstance(item, dict) else None
        distance_object = item.get('distance') if isinstance(item, dict) else None
        duration = duration_object.get('value') if isinstance(duration_object, dict) else None
        distance = distance_object.get('value') if isinstance(distance_object, dict) else None
        valid = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
        # 官方矩阵文档：0可能表示“没有计算结果”，缺字段也不是无路证明。
        explicit_no_route = isinstance(item, dict) and item.get('status') in (2001, '2001', 'no_route')
        known = valid(duration) and duration > 0 and (not isinstance(item, dict) or item.get('status') in (None, 0, '0'))
        return {'fromIndex': i, 'toIndex': j,
                'durationSeconds': duration if known else None,
                'distanceM': distance if valid(distance) else None,
                'status': 'ok' if known else 'no_route' if explicit_no_route else 'error',
                'sourceKind': kind}

    def walking_times(self, origin: Coord, destinations: List[Coord], *,
                      trace_id: Optional[str] = None, stage: str = "A3") -> List[Optional[float]]:
        """单起点多终点 walk matrix;返回与 destinations 同序的 duration 秒列表。"""
        if not destinations:
            return []
        matrix = self.travel_matrix([origin], destinations, trace_id=trace_id, stage=stage)
        by_index = {cell["toIndex"]: cell["durationSeconds"] for cell in matrix["cells"]}
        return [by_index.get(index) for index in range(len(destinations))]

    def isochrone_pois(self, origin: Coord, threshold_seconds: float, query_terms: List[str], *,
                       radii_m: Dict[str, float] | None = None,
                       search_radius_m: float | None = None,
                       max_pages_per_term: int = 2, max_unique: int = 50,
                       trace_id: Optional[str] = None) -> Dict[str, Any]:
        """F57：圈内 POI 真实 API 闭环：区域召回 -> 起点有向矩阵过滤。

        召回半径取实测圈外接半径（无圈时用 search_radius_m/默认 1400m）；可达判定用
        起点->POI 有向步行耗时 <= threshold，不用直线距离代替。
        """
        trace = trace_id or new_trace_id()
        # F61：起点先转 BD09；召回与矩阵都用转换后坐标。
        origin, converted_from = to_baidu_bd09(origin)
        terms = [t.strip() for t in query_terms if t.strip()]
        if not terms:
            raise ServiceError("VALIDATION_ERROR", "queryTerms 不能为空")
        if threshold_seconds <= 0:
            raise ServiceError("VALIDATION_ERROR", "thresholdSeconds 必须大于 0")
        measured = [float(v) for v in (radii_m or {}).values() if v is not None]
        radius = search_radius_m or (max(measured) if measured else 1400.0)
        unique: Dict[str, Dict[str, Any]] = {}
        source_by_key: Dict[str, str] = {}
        raw_count = 0
        page_truncated = False
        invalid_coordinates = False
        for term in terms:
            for page in range(max_pages_per_term):
                params = {
                    "query": term,
                    "location": [origin.lat, origin.lng],
                    "radius": radius,
                    "scope": 2,
                    "pageSize": 20,
                    "pageNum": page,
                }
                result = self._resolve(
                    trace_id=trace, stage="ISO-POI", interface="place_search",
                    interface_version="v2", params=params, pairs=1,
                    invoke=lambda term=term, page=page: self.adapter.place_search(
                        term, location=(origin.lat, origin.lng),
                        radius=int(radius), page_num=page,
                        page_size=20, experiment_id=trace,
                    ),
                )
                items = result.body.get("results") or []
                raw_count += len(items)
                for item in items:
                    if self._place_from_item(item, result.source_kind) is None:
                        invalid_coordinates = True
                        continue
                    loc = item.get("location") or {}
                    key = item.get("uid") or (
                        f"{item.get('name')}|{loc.get('lat')}|{loc.get('lng')}|{item.get('address')}"
                    )
                    if key not in unique:
                        unique[key] = item
                        source_by_key[key] = result.source_kind
                if not items or len(items) < 20:
                    break
                if page == max_pages_per_term - 1:
                    page_truncated = True
        places: List[Dict[str, Any]] = []
        for key, item in list(unique.items())[:max_unique]:
            place = self._place_from_item(item, source_by_key[key])
            if place is not None:
                places.append({"key": key, "place": place})
        matrix = self.travel_matrix([origin], [row['place'].coord for row in places],
            trace_id=trace, stage='ISO-POI') if places else {'cells': []}
        cells = {cell['toIndex']: cell for cell in matrix['cells']}
        reachable: List[Dict[str, Any]] = []
        unreachable: List[Dict[str, Any]] = []
        unknown_count = 0
        for index, row in enumerate(places):
            cell = cells.get(index, {})
            duration = cell.get('durationSeconds') if cell.get('status') == 'ok' else None
            dump = row["place"].model_dump(by_alias=True)
            if duration is not None and duration <= threshold_seconds:
                reachable.append({**dump, "walkSeconds": duration})
            else:
                unknown = duration is None and cell.get('status') != 'no_route'
                unknown_count += int(unknown)
                unreachable.append({**dump, "walkSeconds": duration,
                                    "reason": 'unknown_route' if unknown else "no_route" if duration is None else "over_threshold"})
        reachable.sort(key=lambda row: row["walkSeconds"])
        return {
            "traceId": trace,
            "mode": "live",
            "sourceKind": "derived",
            "reachable": reachable,
            "unreachable": unreachable,
            "pairsUsed": len(places),
            "retrieval": {
                "queryTerms": terms,
                "searchRadiusM": radius,
                "rawCount": raw_count,
                "uniqueCount": len(unique),
                "truncated": len(unique) > max_unique or page_truncated or invalid_coordinates,
                "truncationReason": "max_unique" if len(unique) > max_unique else "page_budget" if page_truncated else 'invalid_coordinates' if invalid_coordinates else None,
                "unknownRoutes": unknown_count,
                "convertedFrom": converted_from,
            },
            "warnings": [],
        }
