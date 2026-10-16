# -*- coding: utf-8 -*-
"""测时等时圈的射线二分核心(纯函数,不直接访问网络)。

契约对应 docs/19 §8：
- 只根据真实测量结果括界/二分；
- 测值缺失、超时或预算不足时返回 failed，半径为空；
- 不把区间中点、固定 800m 或旧缓存半径伪装成测量结果。

本模块不理解百度 API，只接收 ``measure_at(distance_m) -> duration_s | None``。
调用方负责把百度 matrix/direction 或已有 API 缓存包装成回调，并决定后续
partial/degraded 的业务状态。
"""
from dataclasses import dataclass, field
import copy
import math
from typing import Callable, Dict, Iterable, List, Optional, Tuple

MeasureFn = Callable[[float], Optional[float]]
RayMeasureFn = Callable[[float, float], Optional[float]]
BatchMeasureFn = Callable[[List[Tuple[float, float]]], List[Optional[float]]]

ALGORITHM_VERSION = "m2-ray-bisect-v4"
ADAPTIVE_ALGORITHM_VERSION = "m3-adaptive-batched-v1"


def _next_inner_distance(distance_m: float, tol_m: float) -> float:
    # 逐步向内测量；末步实际测量原点，不能假设同点耗时为零。
    return 0.0 if distance_m <= tol_m else distance_m / 2.0


@dataclass
class Probe:
    distance_m: float
    duration_s: Optional[float]
    status: str  # ok | missing | error


@dataclass
class RayBisectResult:
    bearing_deg: Optional[float]
    radius_m: Optional[float]
    status: str  # complete | failed
    reason: str = ""
    lo_m: float = 0.0
    hi_m: float = 0.0
    probes: List[Probe] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "complete" and self.radius_m is not None


def bisect_ray(measure_at: MeasureFn, *, threshold_s: float,
               bearing_deg: Optional[float] = None,
               lo_m: float = 200.0, hi_m: float = 1400.0,
               initial_m: Optional[float] = None,
               tol_m: float = 50.0) -> RayBisectResult:
    """在 [lo_m, hi_m] 内二分单条射线的阈值穿越半径。

    返回 complete 时 ``radius_m`` 必定来自至少一次真实测量形成的区间；
    任一必需测值缺失/异常时返回 failed 且 ``radius_m is None``。
    """
    if not all(math.isfinite(value) for value in (lo_m, hi_m, threshold_s, tol_m)):
        raise ValueError("ray parameters must be finite")
    if lo_m < 0 or hi_m <= lo_m:
        raise ValueError("hi_m must be greater than lo_m")
    if threshold_s <= 0:
        raise ValueError("threshold_s must be positive")
    if tol_m <= 0:
        raise ValueError("tol_m must be positive")
    if initial_m is None:
        initial_m = min(max(800.0, lo_m), hi_m)
    if not (lo_m <= initial_m <= hi_m):
        raise ValueError("initial_m must lie within [lo_m, hi_m]")

    probes: List[Probe] = []

    def probe(d: float) -> Optional[float]:
        try:
            t = measure_at(d)
        except Exception as exc:  # 网络/回调异常也视为测量失败,不写假半径
            probes.append(Probe(d, None, f"error: {type(exc).__name__}"))
            return None
        if t is None or not math.isfinite(t) or t < 0:
            probes.append(Probe(d, None, "missing"))
            return None
        probes.append(Probe(d, t, "ok"))
        return t

    def fail(reason: str) -> RayBisectResult:
        return RayBisectResult(bearing_deg, None, "failed", reason, lo_m, hi_m, probes)

    # 1) 初始探针:对齐既有研究的 800m 起步。
    t_initial = probe(initial_m)
    if t_initial is None:
        return fail("initial_measurement_missing")

    if t_initial <= threshold_s:
        lo_m = initial_m
        # 2a) 初始点可达,向外确认一个超时点。
        t_hi = probe(hi_m)
        if t_hi is None:
            return fail("outer_measurement_missing")
        if t_hi <= threshold_s:
            return fail("threshold_beyond_hi")
    else:
        hi_m = initial_m
        # 2b) 初始点超时,向内确认一个可达点。
        t_lo = probe(lo_m)
        if t_lo is None:
            return fail("inner_measurement_missing")
        while t_lo > threshold_s:
            if lo_m == 0:
                return fail("threshold_below_lo")
            hi_m = lo_m
            lo_m = _next_inner_distance(lo_m, tol_m)
            t_lo = probe(lo_m)
            if t_lo is None:
                return fail("inner_measurement_missing")

    # 3) 已形成 lo 可达、hi 超时的区间;中途测值缺失就失败。
    while hi_m - lo_m > tol_m:
        mid = (lo_m + hi_m) / 2.0
        t_mid = probe(mid)
        if t_mid is None:
            return fail("measurement_missing_during_bisect")
        if t_mid <= threshold_s:
            lo_m = mid
        else:
            hi_m = mid

    return RayBisectResult(bearing_deg, (lo_m + hi_m) / 2.0, "complete",
                           "", lo_m, hi_m, probes)


@dataclass
class IsochroneResult:
    place_id: Optional[str]
    threshold_seconds: float
    status: str  # complete | partial | failed
    radii_m: Dict[float, float] = field(default_factory=dict)
    failed_bearings: List[float] = field(default_factory=list)
    skipped_bearings: List[float] = field(default_factory=list)
    rays: List[RayBisectResult] = field(default_factory=list)
    algorithm_version: str = ALGORITHM_VERSION
    warnings: List[str] = field(default_factory=list)
    pairs_used: int = 0

    @property
    def complete(self) -> bool:
        return self.status == "complete" and bool(self.radii_m)

    def as_dict(self) -> dict:
        return {
            "placeId": self.place_id,
            "thresholdSeconds": self.threshold_seconds,
            "status": self.status,
            "radiiM": {str(k): v for k, v in self.radii_m.items()},
            "failedBearings": self.failed_bearings,
            "skippedBearings": self.skipped_bearings,
            "algorithmVersion": self.algorithm_version,
            "warnings": self.warnings,
            "pairsUsed": self.pairs_used,
        }


def compute_isochrone(measure_ray: RayMeasureFn, *, threshold_s: float,
                      bearings: Optional[Iterable[float]] = None,
                      lo_m: float = 200.0, hi_m: float = 1400.0,
                      tol_m: float = 50.0, max_probes: Optional[int] = None,
                      place_id: Optional[str] = None) -> IsochroneResult:
    """多射线等时圈:每条射线独立二分,失败就返回 partial/failed。

    ``measure_ray(bearing_deg, distance_m) -> duration_s | None`` 由调用方
    包装百度 matrix/live 缓存。测值缺失或预算不足时不写假半径。
    """
    ray_bearings = list(bearings if bearings is not None else range(0, 360, 45))
    result = IsochroneResult(place_id=place_id, threshold_seconds=threshold_s,
                             status="failed")
    used_probes = 0
    def bounded_measure(bearing: float, distance: float) -> Optional[float]:
        nonlocal used_probes
        if max_probes is not None and used_probes >= max_probes:
            return None
        used_probes += 1
        return measure_ray(bearing, distance)
    for index, bearing in enumerate(ray_bearings):
        if max_probes is not None and used_probes >= max_probes:
            result.skipped_bearings.extend(ray_bearings[index:])
            result.warnings.append(f"probe_budget_exhausted:{used_probes}")
            break
        ray = bisect_ray(
            lambda distance, b=bearing: bounded_measure(b, distance),
            threshold_s=threshold_s, bearing_deg=bearing,
            lo_m=lo_m, hi_m=hi_m, tol_m=tol_m,
        )
        result.rays.append(ray)
        if ray.ok and ray.radius_m is not None:
            result.radii_m[bearing] = ray.radius_m
        else:
            result.failed_bearings.append(bearing)
            result.warnings.append(f"ray_failed:{bearing}:{ray.reason}")

    if result.failed_bearings or result.skipped_bearings:
        result.status = "partial" if result.radii_m else "failed"
    else:
        result.status = "complete" if result.radii_m else "failed"
    result.pairs_used = used_probes
    return result


def compute_isochrone_batched(measure_batch: BatchMeasureFn, *,
                              threshold_s: float,
                              bearings: Optional[Iterable[float]] = None,
                              lo_m: float = 200.0, hi_m: float = 1400.0,
                              initial_m: float = 800.0,
                              tol_m: float = 50.0,
                              max_pairs: Optional[int] = None,
                              place_id: Optional[str] = None) -> IsochroneResult:
    """批量测值版多射线二分:同轮所有探针可合并为一次矩阵请求。

    适用于百度 routematrix 批量接口。预算不足或单点缺测时,该射线标记
    failed,绝不回退成固定半径/区间中点。
    """
    ray_bearings = list(bearings if bearings is not None else range(0, 360, 45))
    if not all(math.isfinite(value) for value in (threshold_s, lo_m, hi_m, initial_m, tol_m)):
        raise ValueError("ray parameters must be finite")
    if threshold_s <= 0 or lo_m < 0 or hi_m <= lo_m or tol_m <= 0 or not lo_m <= initial_m <= hi_m:
        raise ValueError("invalid ray bracket or threshold")
    if any(not math.isfinite(b) or not 0 <= b < 360 for b in ray_bearings) or len(set(ray_bearings)) != len(ray_bearings):
        raise ValueError("bearings must be unique and within [0, 360)")
    result = IsochroneResult(place_id=place_id, threshold_seconds=threshold_s,
                             status="failed")
    if not ray_bearings:
        return result

    state: Dict[float, Dict[str, Optional[float]]] = {
        bearing: {"lo": lo_m, "hi": hi_m, "radius": None}
        for bearing in ray_bearings
    }
    used_pairs = 0

    def measure_points(points: List[Tuple[float, float]]) -> tuple:
        # F58：按剩余预算截取可发出的前 N 个点，剩余点才记 skipped；
        # F54 语义保留：未发起测量的点不记 failed、不发 ray_failed 警告，pairs 只计实际发出。
        nonlocal used_pairs
        sendable: List[Tuple[float, float]] = list(points)
        deferred: List[Tuple[float, float]] = []
        if max_pairs is not None and used_pairs + len(points) > max_pairs:
            room = max(0, max_pairs - used_pairs)
            sendable, deferred = list(points[:room]), list(points[room:])
            truncated = [bearing for bearing, _ in deferred
                         if bearing not in result.skipped_bearings
                         and bearing not in result.failed_bearings]
            result.skipped_bearings.extend(truncated)
            result.warnings.append(f"probe_budget_exhausted:{used_pairs}")
            if not sendable:
                return [None] * len(points), [bearing for bearing, _ in points]
        values = measure_batch(sendable)
        values = [value if value is not None and math.isfinite(value) and value >= 0 else None
                  for value in values]
        if len(values) != len(sendable):
            raise ValueError("measure_batch 返回长度与请求不一致")
        used_pairs += len(sendable)
        merged: List[Optional[float]] = []
        cursor = 0
        sent = {(bearing, distance) for bearing, distance in sendable}
        for bearing, distance in points:
            if (bearing, distance) in sent and cursor < len(values):
                merged.append(values[cursor])
                cursor += 1
            else:
                merged.append(None)
        truncated_all = [bearing for bearing, _ in deferred]
        return merged, truncated_all

    # 第一轮:所有方向 800m 初始探针
    values, truncated = measure_points([(bearing, initial_m) for bearing in ray_bearings])
    needs: Dict[float, str] = {}
    for bearing, value in zip(ray_bearings, values):
        if bearing in truncated:
            state[bearing]["lo"] = state[bearing]["hi"] = None
        elif value is None:
            result.failed_bearings.append(bearing)
            result.warnings.append(f"ray_failed:{bearing}:initial_measurement_missing")
            state[bearing]["lo"] = state[bearing]["hi"] = None
        elif value <= threshold_s:
            state[bearing]["lo"] = initial_m
            needs[bearing] = "outer"
        else:
            state[bearing]["hi"] = initial_m
            needs[bearing] = "inner"

    # 第二轮:确认可达内点与超时外点
    inward: Dict[float, float] = {}
    second_points = []
    second_bearings = []
    for bearing in ray_bearings:
        if state[bearing]["lo"] is None and state[bearing]["hi"] is None:
            continue
        if needs[bearing] == "outer":
            second_points.append((bearing, hi_m))
        else:
            second_points.append((bearing, lo_m))
        second_bearings.append(bearing)
    if second_points:
        values, truncated = measure_points(second_points)
        for bearing, value in zip(second_bearings, values):
            if bearing in truncated:
                state[bearing]["lo"] = state[bearing]["hi"] = None
            elif value is None:
                result.failed_bearings.append(bearing)
                result.warnings.append(f"ray_failed:{bearing}:endpoint_measurement_missing")
                state[bearing]["lo"] = state[bearing]["hi"] = None
            elif needs[bearing] == "outer":
                if value <= threshold_s:
                    result.failed_bearings.append(bearing)
                    result.warnings.append(f"ray_failed:{bearing}:threshold_beyond_hi")
                    state[bearing]["lo"] = state[bearing]["hi"] = None
                else:
                    state[bearing]["hi"] = hi_m
            else:
                if value > threshold_s:
                    if lo_m == 0:
                        result.failed_bearings.append(bearing)
                        result.warnings.append(f"ray_failed:{bearing}:threshold_below_lo")
                        state[bearing]["lo"] = state[bearing]["hi"] = None
                    else:
                        state[bearing]["hi"] = lo_m
                        inward[bearing] = _next_inner_distance(lo_m, tol_m)
                else:
                    state[bearing]["lo"] = lo_m

    # 内端点超时只表示边界更近；继续测实际内点，受同一硬预算约束。
    while inward:
        points = list(inward.items())
        values, truncated = measure_points(points)
        inward = {}
        for (bearing, distance), value in zip(points, values):
            if bearing in truncated:
                state[bearing]["lo"] = state[bearing]["hi"] = None
            elif value is None:
                result.failed_bearings.append(bearing)
                result.warnings.append(f"ray_failed:{bearing}:inner_measurement_missing")
                state[bearing]["lo"] = state[bearing]["hi"] = None
            elif value <= threshold_s:
                state[bearing]["lo"] = distance
            elif distance == 0:
                result.failed_bearings.append(bearing)
                result.warnings.append(f"ray_failed:{bearing}:threshold_below_lo")
                state[bearing]["lo"] = state[bearing]["hi"] = None
            else:
                state[bearing]["hi"] = distance
                inward[bearing] = _next_inner_distance(distance, tol_m)

    # 第三阶段:仍在区间内的射线批量同步二分
    while True:
        active = [bearing for bearing in ray_bearings
                  if state[bearing]["lo"] is not None and state[bearing]["hi"] is not None
                  and state[bearing]["hi"] - state[bearing]["lo"] > tol_m]
        if not active:
            break
        mids = [(bearing, (state[bearing]["lo"] + state[bearing]["hi"]) / 2.0)
                for bearing in active]
        values, truncated = measure_points(mids)
        for bearing, value in zip(active, values):
            if bearing in truncated:
                state[bearing]["lo"] = state[bearing]["hi"] = None
                continue
            if value is None:
                result.failed_bearings.append(bearing)
                result.warnings.append(f"ray_failed:{bearing}:measurement_missing_during_bisect")
                state[bearing]["lo"] = state[bearing]["hi"] = None
                continue
            if value <= threshold_s:
                state[bearing]["lo"] = (state[bearing]["lo"] + state[bearing]["hi"]) / 2.0
            else:
                state[bearing]["hi"] = (state[bearing]["lo"] + state[bearing]["hi"]) / 2.0

    for bearing in ray_bearings:
        lo, hi = state[bearing]["lo"], state[bearing]["hi"]
        if lo is not None and hi is not None and hi - lo <= tol_m:
            result.radii_m[bearing] = (lo + hi) / 2.0
        elif bearing not in result.failed_bearings and bearing not in result.skipped_bearings:
            # F54：预算截断（skipped）不再补记 failed/unresolved。
            result.failed_bearings.append(bearing)
            result.warnings.append(f"ray_failed:{bearing}:unresolved")

    result.status = ("complete" if result.radii_m and not result.failed_bearings and not result.skipped_bearings
                     else "partial" if result.radii_m else "failed")
    result.pairs_used = used_pairs
    return result


def compute_isochrone_adaptive(measure_batch: BatchMeasureFn, *, threshold_s: float,
                               bearings=None, lo_m=200.0, hi_m=1400.0,
                               initial_m=800.0, tol_m=25.0, max_pairs=320,
                               place_id=None, on_progress=None) -> IsochroneResult:
    """16向批量起步，按长弦、径向梯度及中间方向实测违规加密。

    同轮探针合批、所有阶段共享硬预算和测值；可选加密未完成时保留已完成的
    基础轮廓并记录精度限制，绝不为缺测方向补造半径。不是全网格时间场重建。
    """
    directions = list(bearings if bearings is not None else [i * 22.5 for i in range(16)])
    if not all(math.isfinite(v) for v in (threshold_s, lo_m, hi_m, initial_m, tol_m)):
        raise ValueError('ray parameters must be finite')
    if threshold_s <= 0 or lo_m < 0 or hi_m <= lo_m or tol_m <= 0 or not lo_m <= initial_m <= hi_m:
        raise ValueError('invalid ray bracket or threshold')
    if not isinstance(max_pairs, int) or max_pairs < 1:
        raise ValueError('max_pairs must be a positive integer')
    if len(set(directions)) != len(directions) or any(not math.isfinite(b) or not 0 <= b < 360 for b in directions):
        raise ValueError('bearings must be unique and within [0, 360)')
    memo = {}
    used = 0
    hi_m = max(hi_m, threshold_s * 2.0)
    initial_m = min(initial_m, hi_m)

    def measured(points):
        nonlocal used
        missing = list(dict.fromkeys(p for p in points if p not in memo))
        send = missing[:max(0, max_pairs - used)]
        if send:
            values = measure_batch(send)
            if len(values) != len(send):
                raise ValueError('measure_batch 返回长度与请求不一致')
            used += len(send)
            for point, value in zip(send, values):
                memo[point] = value if value is not None and math.isfinite(value) and value >= 0 else None
        return [memo.get(p) for p in points]

    def solve(directions):
        # 初始点与两端互不依赖，预取在同一批；后续二分才依赖前轮响应。
        measured([(b, d) for d in (initial_m, lo_m, hi_m) for b in directions])
        return compute_isochrone_batched(measured, threshold_s=threshold_s,
            bearings=directions, lo_m=lo_m, hi_m=hi_m, initial_m=initial_m,
            tol_m=tol_m, max_pairs=None, place_id=place_id)

    base = solve(directions)
    base.algorithm_version = ADAPTIVE_ALGORITHM_VERSION
    base.pairs_used = used
    if not base.complete:
        if used >= max_pairs:
            base.warnings.append('probe_budget_exhausted:base')
        return base
    limited = False
    for _ in range(2):
        # 先发布当前完整实测边界，再进行本轮中间方向检测与二分加密。
        # 副本避免后续原地加密改变已经发布的轮廓/警告。
        if on_progress:
            on_progress(copy.deepcopy(base))
        angles = sorted(base.radii_m)
        candidates = []
        tests = []
        for index, a in enumerate(angles):
            b = angles[(index + 1) % len(angles)]
            gap = (b - a) % 360
            if gap <= 5.625:
                continue
            ra, rb = base.radii_m[a], base.radii_m[b]
            mid = round((a + gap / 2) % 360, 5)
            chord = math.sqrt(ra * ra + rb * rb - 2 * ra * rb * math.cos(math.radians(gap)))
            gradient = abs(rb - ra) / gap
            probe = (mid, .97 * (ra + rb) / 2)
            tests.append((probe, chord, gradient))
        if not tests:
            break
        values = measured([probe for probe, _, _ in tests])
        for (probe, chord, gradient), value in zip(tests, values):
            if value is None:
                limited = True
            if chord > 200 or gradient > 12 or value is not None and value > threshold_s:
                candidates.append((gradient + chord / 200 + (1000 if value is not None and value > threshold_s else 0), probe[0]))
        if not candidates:
            break
        # 为每个新方向预留完整括界/二分的最坏探针量，避免耗尽后丢弃基础圈。
        per_ray = 3 + math.ceil(math.log2((hi_m - lo_m) / tol_m)) + 4
        room = min(48 - len(angles), max(0, max_pairs - used) // per_ray)
        selected = [b for _, b in sorted(candidates, reverse=True)[:room]]
        if len(selected) < len(candidates):
            limited = True
        if not selected:
            break
        refinement = solve(selected)
        base.radii_m.update(refinement.radii_m)
        base.warnings.extend(f'refinement:{w}' for w in refinement.warnings)
        if not refinement.complete:
            limited = True
        base.pairs_used = used
    base.pairs_used = used
    if limited:
        base.warnings.append('adaptive_resolution_limited')
    return base


# ---------- L2 降级链：基于实验标定绕行系数 ρ 的快速估算圈（docs/03、docs/17） ----------

L2_ALGORITHM_VERSION = "l2-detour-v1"
WALKING_SPEED_MPS = 4.2 * 1000.0 / 3600.0  # 4.2 km/h ≈ 1.1667 m/s
DEFAULT_DETOUR_FACTOR = 1.42

# 十六城 E5 实验实测中位绕行系数 ρ 及中心近似坐标范围
CITY_DETOUR_FACTORS: Dict[str, Tuple[float, float, float]] = {
    "长沙": (1.29, 112.98, 28.20),
    "西安": (1.35, 108.95, 34.26),
    "成都": (1.36, 104.07, 30.66),
    "广州": (1.38, 113.26, 23.13),
    "南昌": (1.40, 115.89, 28.68),
    "北京": (1.42, 116.38, 39.92),
    "哈尔滨": (1.44, 126.65, 45.78),
    "深圳": (1.45, 114.06, 22.54),
    "武汉": (1.46, 114.30, 30.59),
    "上海": (1.47, 121.47, 31.23),
    "桂林": (1.58, 110.29, 25.27),
    "重庆": (1.68, 106.55, 29.56),
    "洛阳": (1.73, 112.45, 34.62),
    "兰州": (1.82, 103.82, 36.06),
    "昆山": (1.88, 120.98, 31.38),
    "义乌": (1.98, 120.07, 29.31),
    "遵义": (2.94, 106.93, 27.73),
}


def infer_detour_factor(lng: float, lat: float, city: Optional[str] = None) -> float:
    """根据城市名称或坐标匹配实验标定的绕行系数 ρ，未命中时返回默认 1.42。"""
    if city:
        clean = city.strip().replace("市", "")
        for name, (rho, _c_lng, _c_lat) in CITY_DETOUR_FACTORS.items():
            if name in clean or clean in name:
                return rho
    for _name, (rho, c_lng, c_lat) in CITY_DETOUR_FACTORS.items():
        if abs(lng - c_lng) <= 0.45 and abs(lat - c_lat) <= 0.45:
            return rho
    return DEFAULT_DETOUR_FACTOR


def compute_l2_isochrone(
    origin_lng: float,
    origin_lat: float,
    *,
    threshold_s: float,
    bearings: Optional[Iterable[float]] = None,
    city: Optional[str] = None,
    known_radii: Optional[Dict[float, float]] = None,
    place_id: Optional[str] = None,
) -> IsochroneResult:
    """L2 降级链：零 API 调用快速生成绕行系数估算圈（可融合已知实测方向半径）。"""
    if not math.isfinite(threshold_s) or threshold_s <= 0:
        raise ValueError("threshold_s must be positive")
    ray_bearings = [float(b) for b in (bearings if bearings is not None else range(0, 360, 45))]
    rho = infer_detour_factor(origin_lng, origin_lat, city=city)
    est_radius = round(max(50.0, min(3000.0, (threshold_s * WALKING_SPEED_MPS) / rho)), 1)
    radii: Dict[float, float] = {}
    known = known_radii or {}
    for bearing in ray_bearings:
        if bearing in known and known[bearing] is not None and math.isfinite(known[bearing]):
            radii[bearing] = float(known[bearing])
        else:
            radii[bearing] = est_radius
    return IsochroneResult(
        place_id=place_id,
        threshold_seconds=float(threshold_s),
        status="degraded",
        radii_m=radii,
        failed_bearings=[],
        skipped_bearings=[],
        algorithm_version=L2_ALGORITHM_VERSION,
        warnings=[f"l2-fallback:rho={rho:.2f}"],
        pairs_used=0,
    )

