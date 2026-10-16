"""自适应加密、预算和后台任务回归；只用确定性测时，不调用百度。"""
import copy
import threading
import time

from core.isochrone import compute_isochrone_adaptive, ADAPTIVE_ALGORITHM_VERSION
from core.ratelimit import WindowRateLimiter
from api.app.models.common import Coord
from api.app.services.isochrone_service import IsochroneService
from api.app.storage.derived_cache import DerivedCache
from api.tests.unit.test_isochrone_service import FakeBaidu


def test_each_refinement_publishes_independent_measured_boundary_before_queries():
    published = []
    initial = {i * 22.5 for i in range(16)}

    def measure(points):
        if any(b not in initial for b, _ in points):
            assert published, '必须先发布基础实测圈才能查询加密探针'
            assert len(published[0].radii_m) == 16
        return [d * 900 / 800 for _, d in points]

    result = compute_isochrone_adaptive(measure, threshold_s=900, max_pairs=320,
                                        on_progress=published.append)
    assert result.complete
    assert len(published) == 2
    assert len(published[0].radii_m) == 16
    assert len(published[1].radii_m) > 16
    assert published[0].radii_m is not result.radii_m
    assert published[1].warnings is not result.warnings


def test_midpoint_probe_discovers_notch_and_budget_is_shared():
    sent = []
    progress = []
    def measure(points):
        sent.extend(points)
        return [d / (350 if 8 < b < 15 else 800) * 900 for b, d in points]
    result = compute_isochrone_adaptive(measure, threshold_s=900, max_pairs=320,
        on_progress=lambda r: progress.append(copy.deepcopy(r.as_dict())))
    assert result.complete
    assert result.algorithm_version == ADAPTIVE_ALGORITHM_VERSION
    assert len(progress[0]['radiiM']) == 16
    assert len(result.radii_m) > 16
    assert abs(result.radii_m[11.25] - 350) <= 25
    assert result.pairs_used == len(sent) <= 320
    assert len(sent) == len(set(sent))  # 探针共享、无重复计费


def test_optional_refinement_budget_preserves_measured_coarse_boundary():
    result = compute_isochrone_adaptive(lambda pts: [d * 900 / 800 for _, d in pts],
                                        threshold_s=900, max_pairs=150)
    assert result.complete and len(result.radii_m) == 16
    assert result.pairs_used <= 150
    assert 'adaptive_resolution_limited' in result.warnings


def test_missing_base_probes_do_not_create_a_polygon():
    result = compute_isochrone_adaptive(lambda pts: [None] * len(pts), threshold_s=900, max_pairs=12)
    assert result.status == 'failed'
    assert result.radii_m == {}
    assert result.pairs_used == 12


def test_route_count_limiter_bounds_every_window():
    now = [0.0]
    limiter = WindowRateLimiter(10, clock=lambda: now[0], sleeper=lambda s: now.__setitem__(0, now[0] + s))
    assert limiter.acquire(8) == 0
    assert limiter.acquire(2) == 0
    assert limiter.acquire(8) >= 1.05
    assert now[0] >= 1.05


def test_fifty_routes_use_a_three_second_window_not_fifty_per_second():
    now = [0.0]
    limiter = WindowRateLimiter(50, window_s=3.15, clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s))
    assert limiter.acquire(50) == 0
    assert limiter.acquire(50) >= 3.15
    assert limiter.acquire(50) >= 3.15
    assert now[0] >= 6.3


def test_rate_limit_extends_real_route_window_and_success_recovers_slowly():
    now = [0.0]
    limiter = WindowRateLimiter(50, window_s=4.2, clock=lambda: now[0],
        sleeper=lambda delay: now.__setitem__(0, now[0] + delay))
    limiter.acquire(50)
    limiter.on_rate_limited()
    assert limiter.acquire(50) >= 8.4
    for _ in range(9):
        limiter.on_success()
    assert limiter.window_s == 8.4
    limiter.on_success()
    assert 4.2 < limiter.window_s < 8.4
    for _ in range(1000):
        limiter.on_success()
    assert limiter.window_s == 4.2


def test_matrix_window_configuration_overrides_per_second_default(tmp_path, monkeypatch):
    from api.app.config import Settings
    from api.app.services.baidu_service import BaiduService
    monkeypatch.setenv('BAIDU_MATRIX_ROUTES_PER_WINDOW', '50')
    monkeypatch.setenv('BAIDU_MATRIX_WINDOW_SECONDS', '3.15')
    settings = Settings(baidu_ak='fake', baidu_sk='', request_timeout_s=1,
        cache_db=str(tmp_path / 'c.db'), ledger_db=str(tmp_path / 'l.db'))
    service = BaiduService(settings)
    assert service._matrix_batch_size == 50
    assert service._interface_limits['matrix_walking'].capacity == 50
    assert service._interface_limits['matrix_walking'].window_s == 3.15
    assert service._interface_limits['place_search'].capacity == 3


def test_identical_background_requests_share_one_job_and_publish_measured_progress(tmp_path):
    gate = threading.Event()
    class Slow(FakeBaidu):
        def travel_matrix(self, *args, **kwargs):
            gate.wait(2)
            return super().travel_matrix(*args, **kwargs)
    fake = Slow()
    service = IsochroneService(fake, cache=DerivedCache(str(tmp_path / 'derived.db')))
    origin = Coord(lng=116.33, lat=40.07)
    first = service.run(origin, threshold_seconds=900, adaptive=True, l2_first=True, max_pairs=160)
    second = service.run(origin, threshold_seconds=900, adaptive=True, l2_first=True, max_pairs=160)
    assert first['taskId'] == second['taskId']
    gate.set()
    for _ in range(200):
        result = service.get_task_status(first['taskId'])
        if result['backgroundStatus'] != 'running':
            break
        time.sleep(.005)
    assert result['backgroundStatus'] == 'completed'
    assert result['status'] == 'complete'
    assert len(result['radiiM']) >= 16
    assert result['pairsUsed'] <= 160
    assert service.cache.get_by_task(first['taskId']).result['radiiM'] == result['radiiM']
    service._workers.shutdown(wait=True)


def test_partial_rate_limit_retries_cached_and_missing_cells(monkeypatch):
    monkeypatch.setattr('api.app.services.isochrone_service.time.sleep', lambda _: None)
    class Partial(FakeBaidu):
        def travel_matrix(self, *args, **kwargs):
            result = super().travel_matrix(*args, **kwargs)
            if self.calls == 1:
                result['cells'][-1]['durationSeconds'] = None
                result['errors'] = [{'code': 'RATE_LIMITED', 'retryAfterSeconds': 1}]
            return result
    service = IsochroneService(Partial())
    result = service.run(Coord(lng=116.33, lat=40.07), threshold_seconds=900,
                         _retry_rate_limit=True)
    assert result['status'] == 'complete'
    assert not any('upstream:RATE_LIMITED' == w for w in result['warnings'])


def test_matrix_batches_are_bounded_concurrent_and_keep_destination_indices(tmp_path):
    from api.tests.unit.test_gateway_reliability import service as make_service
    from core.baidu_client import ApiResult
    service = make_service(tmp_path)
    lock = threading.Lock()
    active = peak = 0
    class SlowAdapter:
        def routematrix(self, starts, ends, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.03)
            with lock:
                active -= 1
            return ApiResult(True, 0, '', {'status': 0, 'result': [
                {'duration': {'value': int(round((lng - 116) * 1000))}, 'distance': {'value': 100}}
                for _, lng in ends]})
    service.adapter = SlowAdapter()
    service._matrix_parallel = True
    service._matrix_batch_size = 3
    result = service.travel_matrix([Coord(lng=116, lat=40)],
        [Coord(lng=116 + i / 1000, lat=40) for i in range(1, 13)])
    assert peak == 2
    assert [c['toIndex'] for c in result['cells']] == list(range(12))
    assert [c['durationSeconds'] for c in result['cells']] == list(range(1, 13))


def test_cached_coarse_circle_does_not_suppress_missing_refinement():
    gate = threading.Event()
    class Cached(FakeBaidu):
        def __init__(self):
            super().__init__()
            self.items = {}
            self.block = False
        def travel_matrix(self, origins, destinations, **kwargs):
            if self.block:
                gate.wait(2)
            result = super().travel_matrix(origins, destinations, **kwargs)
            for d, cell in zip(destinations, result['cells']):
                self.items[(d.lng, d.lat)] = cell['durationSeconds']
            return result
        def peek_matrix(self, origins, destinations, allow_partial=False):
            values = [self.items.get((d.lng, d.lat)) for d in destinations]
            if any(v is None for v in values) and not allow_partial:
                return None
            return {'cells': [{'toIndex': i, 'durationSeconds': v, 'status': 'ok' if v is not None else 'error'}
                for i, v in enumerate(values)], 'responseHashes': ['fake-hash']}
    fake = Cached()
    service = IsochroneService(fake)
    origin = Coord(lng=116.33, lat=40.07)
    service.run(origin, threshold_seconds=900, bearings=[i * 22.5 for i in range(16)], hi_m=1800, tol_m=25, max_pairs=320)
    fake.block = True
    first = service.run(origin, threshold_seconds=900, adaptive=True, l2_first=True, tol_m=25, max_pairs=320)
    assert first['backgroundStatus'] == 'running'
    assert first['status'] == 'complete'  # 已缓存实测基础圈，后台仍在补测
    gate.set()
    service._workers.shutdown(wait=True)
    assert len(service.get_task_status(first['taskId'])['radiiM']) > 16
