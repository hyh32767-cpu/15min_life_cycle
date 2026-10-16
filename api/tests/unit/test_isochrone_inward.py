import pytest

from core.isochrone import bisect_ray, compute_isochrone_batched


def test_short_and_long_rays_find_measured_brackets():
    targets = {b: r for b, r in zip(range(0, 360, 45), [20, 80, 150, 210, 350, 600, 800, 1000])}
    calls = []

    def measure(points):
        calls.extend(points)
        return [d * 300 / targets[b] for b, d in points]

    result = compute_isochrone_batched(measure, threshold_s=300, max_pairs=64)
    assert result.status == 'complete'
    assert result.pairs_used == len(calls) <= 64
    for bearing, target in targets.items():
        assert abs(result.radii_m[bearing] - target) <= 25
    assert (0, 0) in calls  # 即使原点也由测量回调提供耗时。


def test_missing_inward_probe_does_not_fill_failed_direction():
    def measure(points):
        return [None if b == 90 and d == 100 else d * 3 for b, d in points]

    result = compute_isochrone_batched(measure, threshold_s=300, bearings=[0, 90])
    assert result.status == 'partial'
    assert result.failed_bearings == [90]
    assert 90 not in result.radii_m
    assert abs(result.radii_m[0] - 100) <= 25


def test_inward_probes_obey_the_same_hard_budget():
    calls = []

    def measure(points):
        calls.extend(points)
        return [d * 6 for _, d in points]

    result = compute_isochrone_batched(measure, threshold_s=300,
                                       bearings=[0, 45, 90, 135], max_pairs=9)
    assert len(calls) == result.pairs_used == 9
    assert result.status == 'failed'
    assert result.radii_m == {}
    assert result.failed_bearings == []
    assert sorted(result.skipped_bearings) == [0, 45, 90, 135]


@pytest.mark.parametrize('origin_duration', [None, 301])
def test_origin_is_not_assumed_reachable(origin_duration):
    def duration(d):
        return origin_duration if d == 0 else 1000

    single = bisect_ray(duration, threshold_s=300)
    batch = compute_isochrone_batched(lambda points: [duration(d) for _, d in points],
                                      threshold_s=300, bearings=[0])
    assert single.status == batch.status == 'failed'
    assert single.radius_m is None
    assert batch.radii_m == {}
    assert batch.failed_bearings == [0]


@pytest.mark.parametrize('target', [15, 90, 180])
def test_single_and_batch_agree_below_original_inner_endpoint(target):
    def duration(d):
        return d * 300 / target

    single = bisect_ray(duration, threshold_s=300, tol_m=1)
    batch = compute_isochrone_batched(lambda points: [duration(d) for _, d in points],
                                      threshold_s=300, bearings=[0], tol_m=1)
    assert single.status == batch.status == 'complete'
    assert single.radius_m == batch.radii_m[0]
    assert abs(single.radius_m - target) <= .5
