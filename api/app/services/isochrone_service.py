# -*- coding: utf-8 -*-
"""POI 等时圈任务服务:批量测值、失败语义、快速预估先行与后台全量生成、派生缓存。"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from core.coord import dest_at
from core.time_contour import reconstruct_time_contours, VERSION as CONTOUR_VERSION
from core.isochrone import (
    ALGORITHM_VERSION,
    ADAPTIVE_ALGORITHM_VERSION,
    compute_isochrone_adaptive,
    compute_isochrone_batched,
    compute_l2_isochrone,
)

from ..models.common import Coord
from ..storage.derived_cache import DerivedCache, derived_key
from ..storage.ledger import new_trace_id
from .baidu_service import BaiduService, to_baidu_bd09
from .errors import ServiceError


def _isochrone_report(result, *, threshold_seconds: float, origin: Coord) -> Dict:
    """F56：等时圈报告。面积/周长由实测射线多边形重建，为近似值，不声称完整路网面积。"""
    import math
    radii = sorted(float(v) for v in (result.radii_m or {}).values())
    bearings = sorted(float(k) for k in (result.radii_m or {}).keys())
    area_m2: float | None = None
    perimeter_m: float | None = None
    if len(bearings) >= 3 and result.status in ('complete', 'degraded'):
        lat_ref = math.radians(origin.lat)
        pts = []
        for bearing in bearings:
            radius = float(result.radii_m.get(bearing, result.radii_m.get(int(bearing) if bearing == int(bearing) else bearing)))
            lat, lng = dest_at(origin.lng, origin.lat, bearing, radius)
            pts.append((lng, lat))
        xs = [(lng - origin.lng) * 111320.0 * math.cos(lat_ref) for lng, _ in pts]
        ys = [(lat - origin.lat) * 111320.0 for _, lat in pts]
        area_m2 = abs(sum(xs[i] * ys[(i + 1) % len(xs)] - xs[(i + 1) % len(xs)] * ys[i]
                          for i in range(len(xs)))) / 2.0
        perimeter_m = sum(
            math.hypot(xs[(i + 1) % len(xs)] - xs[i], ys[(i + 1) % len(ys)] - ys[i])
            for i in range(len(xs)))
    count = len(radii)
    if not radii:
        median: float | None = None
    elif count % 2 == 1:
        median = radii[count // 2]
    else:
        median = (radii[count // 2 - 1] + radii[count // 2]) / 2.0
    note = (
        "按距离估算的近似范围，不代表路线测量已完成"
        if result.status == "degraded"
        else "实测射线重建近似边界，非完整路网可达面积"
    )
    return {
        "thresholdSeconds": float(threshold_seconds),
        "origin": origin.model_dump(by_alias=True),
        "algorithmVersion": result.algorithm_version,
        "effectiveBearings": count,
        "failedBearings": list(result.failed_bearings),
        "skippedBearings": list(result.skipped_bearings),
        "maxRadiusM": max(radii) if radii else None,
        "minRadiusM": min(radii) if radii else None,
        "medianRadiusM": median,
        "approxAreaM2": area_m2 if result.status in ("complete", "degraded") else None,
        "approxPerimeterM": perimeter_m if result.status in ("complete", "degraded") else None,
        "approxNote": note,
        "pairsUsed": result.pairs_used,
    }


class IsochroneService:
    def __init__(self, baidu: BaiduService, *, cache: Optional[DerivedCache] = None) -> None:
        self.baidu = baidu
        self.cache = cache
        self._bg_lock = threading.Lock()
        self._bg_tasks: Dict[str, Dict] = {}
        self._bg_keys: Dict[str, str] = {}
        self._bg_times: Dict[str, float] = {}
        self._workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix='isochrone')

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """查询等时圈任务状态（支持快速预估先行后轮询后台全量实测结果）。"""
        with self._bg_lock:
            bg = self._bg_tasks.get(task_id)
            if bg is not None:
                return dict(bg)
        if self.cache is not None:
            record = self.cache.get_by_task(task_id)
            if record is not None:
                payload = dict(record.result)
                payload["backgroundStatus"] = "completed"
                return payload
        return None

    def _build_l2_payload(
        self,
        origin: Coord,
        *,
        threshold_seconds: float,
        ray_bearings: List[float],
        place_id: Optional[str],
        trace: str,
        converted_from: Optional[str],
        known_radii: Optional[Dict[float, float]] = None,
        extra_warnings: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        background_status: str = "idle",
    ) -> Dict:
        l2_res = compute_l2_isochrone(
            origin.lng,
            origin.lat,
            threshold_s=threshold_seconds,
            bearings=ray_bearings,
            known_radii=known_radii,
            place_id=place_id,
        )
        payload = l2_res.as_dict()
        payload["taskId"] = task_id or uuid.uuid4().hex[:12]
        payload["placeId"] = place_id
        payload["cacheHit"] = False
        payload["expiresAt"] = None
        payload["traceId"] = trace
        payload["upstreamResponseHashes"] = []
        payload["mode"] = "live"
        payload["sourceKind"] = "derived"
        payload["origin"] = origin.model_dump(by_alias=True)
        payload["backgroundStatus"] = background_status
        warnings = list(payload.get("warnings") or [])
        if converted_from:
            warnings.append(f"origin-converted:{converted_from}->BD09")
        if extra_warnings:
            warnings.extend(extra_warnings)
        payload["warnings"] = warnings
        payload["report"] = _isochrone_report(
            l2_res, threshold_seconds=threshold_seconds, origin=origin
        )
        return payload

    def run(self, origin: Coord, *, threshold_seconds: float,
            place_id: Optional[str] = None,
            bearings: Optional[List[float]] = None,
            lo_m: float = 200.0, hi_m: float = 1400.0,
            initial_m: float = 800.0, tol_m: float = 50.0,
            max_pairs: int = 64,
            cache_only: bool = False,
            l2_first: bool = False,
            allow_l2_fallback: bool = False,
            adaptive: bool = False, frontier: bool = False,
            trace_id: Optional[str] = None,
            _on_progress=None, _retry_rate_limit=False) -> Dict:
        if frontier:
            from .grid_frontier_service import GridFrontierService
            return GridFrontierService(self).run(origin,threshold_seconds=threshold_seconds,
                max_pairs=max_pairs,l2_first=l2_first,trace_id=trace_id,cache_only=cache_only)
        trace = trace_id or new_trace_id()
        raw_origin = origin
        origin, converted_from = to_baidu_bd09(origin)
        ray_bearings = list(bearings if bearings is not None else
                            ([i * 22.5 for i in range(16)] if adaptive else range(0, 360, 45)))
        algorithm_version = ADAPTIVE_ALGORITHM_VERSION if adaptive else ALGORITHM_VERSION

        if l2_first and not cache_only:
            job_key = derived_key(algorithm='isochrone-job', algorithm_version=algorithm_version,
                input_hashes={'origin': str(origin.model_dump())}, params={
                    'seconds': threshold_seconds, 'bearings': ray_bearings, 'lo': lo_m,
                    'hi': hi_m, 'initial': initial_m, 'tol': tol_m, 'budget': max_pairs, 'place': place_id,
                    'contourVersion': CONTOUR_VERSION})
            with self._bg_lock:
                for key, task in list(self._bg_keys.items()):
                    if self._bg_tasks[task].get('backgroundStatus') != 'running' and time.monotonic() - self._bg_times[task] > 600:
                        self._bg_keys.pop(key)
                        self._bg_tasks.pop(task, None)
                        self._bg_times.pop(task, None)
                existing = self._bg_keys.get(job_key)
                if existing and self._bg_tasks[existing].get('backgroundStatus') == 'running':
                    return dict(self._bg_tasks[existing])
                if sum(p.get('backgroundStatus') == 'running' for p in self._bg_tasks.values()) >= 2:
                    raise ServiceError('SERVICE_BUSY', '正在生成其他步行范围，请稍后重试', http_status=503,
                                       retryable=True, retry_after=3)
            cached_try = self.run(
                origin,
                threshold_seconds=threshold_seconds,
                place_id=place_id,
                bearings=ray_bearings,
                lo_m=lo_m,
                hi_m=hi_m,
                initial_m=initial_m,
                tol_m=tol_m,
                max_pairs=max_pairs,
                cache_only=True,
                l2_first=False,
                trace_id=trace,
                adaptive=adaptive,
            )
            if cached_try.get("status") == "complete" and 'upstream:CACHE_MISS' not in cached_try.get('warnings', []):
                cached_try["backgroundStatus"] = "completed"
                return cached_try

            task_id = uuid.uuid4().hex[:12]
            known_partial = {
                float(k): float(v)
                for k, v in (cached_try.get("radiiM") or {}).items()
                if v is not None
            }
            l2_payload = self._build_l2_payload(
                origin,
                threshold_seconds=threshold_seconds,
                ray_bearings=[float(b) for b in ray_bearings],
                place_id=place_id,
                trace=trace,
                converted_from=converted_from,
                known_radii=known_partial,
                extra_warnings=["l2-preview:background-measuring"],
                task_id=task_id,
                background_status="running",
            )
            if cached_try.get('status') == 'complete':
                # 已缓存的实测基础圈可立即显示，但缺失的加密方向仍须后台补测。
                l2_payload = {**cached_try, 'taskId': task_id, 'backgroundStatus': 'running'}
            with self._bg_lock:
                # 缓存探测期间另一请求可能已提交相同任务，再检查一次。
                existing = self._bg_keys.get(job_key)
                if existing and self._bg_tasks[existing].get('backgroundStatus') == 'running':
                    return dict(self._bg_tasks[existing])
                if sum(p.get('backgroundStatus') == 'running' for p in self._bg_tasks.values()) >= 2:
                    raise ServiceError('SERVICE_BUSY', '正在生成其他步行范围，请稍后重试', http_status=503, retryable=True, retry_after=3)
                # 有界保存近期任务，运行中的任务不会被移除。
                for old in list(self._bg_tasks):
                    if len(self._bg_tasks) < 128:
                        break
                    if self._bg_tasks[old].get('backgroundStatus') != 'running':
                        self._bg_tasks.pop(old)
                        self._bg_times.pop(old, None)
                        self._bg_keys = {k: v for k, v in self._bg_keys.items() if v != old}
                self._bg_tasks[task_id] = dict(l2_payload)
                self._bg_keys[job_key] = task_id
                self._bg_times[task_id] = time.monotonic()

            def publish(payload):
                with self._bg_lock:
                    self._bg_tasks[task_id] = {**payload, 'taskId': task_id, 'backgroundStatus': 'running'}

            def _bg_worker() -> None:
                try:
                    full = self.run(
                        raw_origin,
                        threshold_seconds=threshold_seconds,
                        place_id=place_id,
                        bearings=ray_bearings,
                        lo_m=lo_m,
                        hi_m=hi_m,
                        initial_m=initial_m,
                        tol_m=tol_m,
                        max_pairs=max_pairs,
                        cache_only=False,
                        l2_first=False,
                        allow_l2_fallback=False,
                        adaptive=adaptive,
                        _on_progress=publish,
                        _retry_rate_limit=True,
                        trace_id=trace,
                    )
                    if self.cache is not None and full['status'] == 'complete':
                        record = self.cache.get_by_task(full['taskId'])
                        if record is not None:
                            self.cache.register_task(task_id, record.key)
                    full["taskId"] = task_id
                    full["backgroundStatus"] = "completed" if full['status'] == 'complete' else 'degraded'
                    with self._bg_lock:
                        self._bg_tasks[task_id] = full
                except Exception as exc:
                    with self._bg_lock:
                        cur = dict(self._bg_tasks.get(task_id) or l2_payload)
                        cur["backgroundStatus"] = "degraded"
                        ws = list(cur.get("warnings") or [])
                        ws.append(f"background-error:{getattr(exc, 'code', type(exc).__name__)}")
                        cur["warnings"] = ws
                        self._bg_tasks[task_id] = cur

            self._workers.submit(_bg_worker)
            return l2_payload

        upstream_error: Optional[str] = None
        upstream_hashes: List[str] = []
        peek_hashes: List[str] = []
        source_expirations: List[Optional[str]] = []
        deadline = time.monotonic() + 180

        def _destinations(points: List[Tuple[float, float]]) -> List[Coord]:
            out = []
            for bearing, distance in points:
                lat, lng = dest_at(origin.lng, origin.lat, bearing, distance)
                out.append(Coord(lng=lng, lat=lat, crs="BD09"))
            return out

        def _peek(points: List[Tuple[float, float]]) -> Optional[List[Optional[float]]]:
            nonlocal upstream_error
            peek_fn = getattr(self.baidu, "peek_matrix", None)
            if peek_fn is None:
                return None
            try:
                peeked_result = (peek_fn([origin], _destinations(points), allow_partial=True)
                                 if cache_only else peek_fn([origin], _destinations(points)))
            except TypeError:
                peeked_result = peek_fn([origin], _destinations(points))
            if peeked_result is None:
                return None
            by_index = {cell["toIndex"]: cell["durationSeconds"]
                        for cell in peeked_result["cells"]}
            peek_hashes.extend(peeked_result.get("responseHashes", []))
            source_expirations.append(peeked_result.get("expiresAt"))
            if cache_only and any(cell.get('status') == 'error' for cell in peeked_result['cells']):
                upstream_error = 'CACHE_MISS'
            return [by_index.get(index) for index in range(len(points))]

        measurements = {}

        def _measure_batch(points: list) -> list:
            nonlocal upstream_error
            if time.monotonic() >= deadline:
                upstream_error = 'UPSTREAM_TIMEOUT'
                return [None] * len(points)
            pred = _peek(points)
            if pred is not None:
                return pred
            destinations = _destinations(points)
            if cache_only:
                upstream_error = 'CACHE_MISS'
                return [None] * len(points)
            try:
                for attempt in range(2):
                    try:
                        matrix = self.baidu.travel_matrix([origin], destinations, trace_id=trace, stage='isochrone')
                    except ServiceError as exc:
                        if not (_retry_rate_limit and attempt == 0 and exc.code == 'RATE_LIMITED'
                                and time.monotonic() + (exc.retry_after or 5) < deadline):
                            raise
                        time.sleep(min(60, exc.retry_after or 5) + .1)
                        continue
                    # 多批矩阵可部分成功：只补缺失OD，不能把批次错误吞成普通缺测。
                    errors = matrix.get('errors', [])
                    limited = next((e for e in errors if e['code'] == 'RATE_LIMITED'), None)
                    if limited and _retry_rate_limit and attempt == 0:
                        delay = min(60, limited.get('retryAfterSeconds') or 5)
                        if time.monotonic() + delay < deadline:
                            time.sleep(delay + .1)
                            continue
                    if errors:
                        upstream_error = errors[0]['code']
                    break
                upstream_hashes.extend(matrix.get("responseHashes", []))
                source_expirations.append(matrix.get("expiresAt"))
                by_index = {cell["toIndex"]: cell["durationSeconds"] for cell in matrix["cells"]}
                return [by_index.get(index) for index in range(len(destinations))]
            except ServiceError as exc:
                upstream_error = exc.code
                return [None] * len(points)

        def measure_batch(points: list) -> list:
            values = _measure_batch(points)
            for point, value in zip(points, values):
                if value is not None:
                    measurements[tuple(point)] = max(measurements.get(tuple(point), value), value)
            return values

        def reconstruction(snapshot):
            return reconstruct_time_contours(
                [(b, d, t) for (b, d), t in measurements.items()], snapshot.radii_m,
                threshold_s=threshold_seconds, lng=origin.lng, lat=origin.lat)

        def progress(partial):
            if _on_progress:
                _on_progress({**partial.as_dict(), 'origin': origin.model_dump(by_alias=True),
                    'traceId': trace, 'cacheHit': False, 'sourceKind': 'derived', 'mode': 'live',
                    'expiresAt': min(source_expirations) if source_expirations and all(source_expirations) else None,
                    'reconstruction': reconstruction(partial),
                    'report': _isochrone_report(partial, threshold_seconds=threshold_seconds, origin=origin)})

        result = (compute_isochrone_adaptive if adaptive else compute_isochrone_batched)(
            measure_batch, threshold_s=threshold_seconds,
            bearings=ray_bearings, lo_m=lo_m, hi_m=hi_m,
            initial_m=initial_m, tol_m=tol_m, max_pairs=max_pairs,
            place_id=place_id,
            **({'on_progress': progress} if adaptive else {}),
        )
        effective_upstream_hashes = sorted(set(upstream_hashes + peek_hashes))
        key = derived_key(
            algorithm="isochrone-batched",
            algorithm_version=algorithm_version,
            input_hashes={"origin": f"{origin.lat:.6f},{origin.lng:.6f}"},
            params={
                "thresholdSeconds": float(threshold_seconds),
                "bearings": [float(b) for b in ray_bearings],
                "loM": float(lo_m), "hiM": float(hi_m),
                "initialM": float(initial_m), "tolM": float(tol_m),
                "maxPairs": int(max_pairs),
                "mode": "live",
                "apiVersion": "matrix_walking/v2",
                "contourVersion": CONTOUR_VERSION,
                "upstreamResponseHashes": effective_upstream_hashes,
            },
        )
        if self.cache is not None and effective_upstream_hashes and not upstream_error:
            cached = self.cache.get(key)
            if cached is not None and not cached.is_expired(ttl_s=86400.0):
                payload = dict(cached.result)
                payload["cacheHit"] = True
                payload["expiresAt"] = min(source_expirations) if source_expirations and all(source_expirations) else payload.get("expiresAt")
                payload["traceId"] = trace
                payload["taskId"] = uuid.uuid4().hex[:12]
                payload["placeId"] = place_id
                payload["upstreamResponseHashes"] = effective_upstream_hashes
                payload["pairsUsed"] = 0
                warnings = list(payload.get("warnings") or [])
                warnings.append("derived-cache-hit:ledger-cost-0")
                payload["warnings"] = warnings
                self.cache.register_task(payload["taskId"], key)
                return payload

        if allow_l2_fallback and result.status in ("failed", "partial") and upstream_error in ("QUOTA_EXCEEDED", "RATE_LIMITED", "UPSTREAM_ERROR", "UPSTREAM_NETWORK", "UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE", "SERVICE_BUSY"):
            known_partial = {float(k): float(v) for k, v in (result.radii_m or {}).items() if v is not None}
            return self._build_l2_payload(
                origin,
                threshold_seconds=threshold_seconds,
                ray_bearings=[float(b) for b in ray_bearings],
                place_id=place_id,
                trace=trace,
                converted_from=converted_from,
                known_radii=known_partial,
                extra_warnings=[f"upstream:{upstream_error}", "l2-degraded-fallback"],
                background_status="degraded",
            )

        payload = result.as_dict()
        payload['reconstruction'] = reconstruction(result)
        payload["taskId"] = uuid.uuid4().hex[:12]
        payload["placeId"] = place_id
        payload["cacheHit"] = False
        payload["expiresAt"] = min(source_expirations) if source_expirations and all(source_expirations) else None
        payload["traceId"] = trace
        payload["upstreamResponseHashes"] = effective_upstream_hashes
        payload["mode"] = "live"
        payload["sourceKind"] = ("api-cache" if peek_hashes and not upstream_hashes and not upstream_error
                                 else "mixed" if peek_hashes and upstream_hashes else "derived")
        payload["origin"] = origin.model_dump(by_alias=True)
        payload["backgroundStatus"] = "completed" if result.status == "complete" else "degraded"
        warnings = list(payload.get("warnings") or [])
        if converted_from:
            warnings.append(f"origin-converted:{converted_from}->BD09")
        if upstream_error:
            warnings.append(f"upstream:{upstream_error}")
        payload["warnings"] = warnings
        payload["report"] = _isochrone_report(result, threshold_seconds=threshold_seconds, origin=origin)
        if self.cache is not None and result.status == "complete" and not upstream_error:
            self.cache.put(
                key=key,
                algorithm="isochrone-batched",
                algorithm_version=algorithm_version,
                dependencies={"upstreamResponseHashes": effective_upstream_hashes},
                result=payload,
            )
            self.cache.register_task(payload["taskId"], key)
        return payload
