# -*- coding: utf-8 -*-
from core.isochrone import compute_isochrone_batched


def test_batched_isochrone_complete_recovers_radii():
    def measure(points):
        return [distance * (900.0 / 800.0) for _bearing, distance in points]

    result = compute_isochrone_batched(measure, threshold_s=900.0,
                                       bearings=[0, 45, 90, 135], tol_m=1.0)
    assert result.status == "complete"
    assert len(result.radii_m) == 4
    assert all(abs(radius - 800.0) <= 1.0 for radius in result.radii_m.values())


def test_batched_isochrone_missing_ray_is_partial_without_fake_radius():
    def measure(points):
        return [None if bearing == 90 else distance * (900.0 / 800.0)
                for bearing, distance in points]

    result = compute_isochrone_batched(measure, threshold_s=900.0,
                                       bearings=[0, 45, 90, 135], tol_m=1.0)
    assert result.status == "partial"
    assert 90 in result.failed_bearings
    assert 90 not in result.radii_m
    assert len(result.radii_m) == 3


def test_batched_isochrone_budget_does_not_fabricate_radius():
    def measure(points):
        return [distance * (900.0 / 800.0) for _bearing, distance in points]

    result = compute_isochrone_batched(measure, threshold_s=900.0,
                                       bearings=[0, 45, 90, 135],
                                       tol_m=1.0, max_pairs=3)
    assert result.status == "failed"
    assert result.radii_m == {}
    assert result.warnings


def test_budget_exhaustion_marks_skipped_not_failed():
    # F54：预算主动截断记 skippedBearings，不记 failed，不伪造 ray_failed 警告。
    from core.isochrone import compute_isochrone_batched
    calls = {"n": 0}

    def measure_batch(points):
        calls["n"] += len(points)
        return [100.0 for _ in points]

    result = compute_isochrone_batched(
        measure_batch, threshold_s=900.0, bearings=[0, 45, 90, 135],
        max_pairs=1,
    )
    # F58：剩余 1 对预算发出首个探针（bearing 0），其余整批 skipped；
    # bearing 0 二轮 hi 探针同样被预算截断（未测量），同样记 skipped，不记 failed、不伪造 ray_failed。
    assert result.status == "failed"
    assert result.pairs_used == 1
    assert calls["n"] == 1
    assert sorted(result.skipped_bearings) == [0, 45, 90, 135]
    assert result.failed_bearings == []
    assert not [w for w in result.warnings if w.startswith("ray_failed")]
    assert not [w for w in result.warnings if w.startswith("ray_failed")]
    assert any(w.startswith("probe_budget_exhausted") for w in result.warnings)


def test_partial_budget_measures_what_fits():
    # F58：max_pairs=4、8 bearings 时发出前 4 个探针，剩余 4 个 skipped；pairsUsed==实际请求数。
    from core.isochrone import compute_isochrone_batched
    calls = {"n": 0}

    def measure_batch(points):
        calls["n"] += len(points)
        return [100.0 for _ in points]

    result = compute_isochrone_batched(
        measure_batch, threshold_s=900.0,
        bearings=[0, 45, 90, 135, 180, 225, 270, 315],
        max_pairs=4,
    )
    assert result.pairs_used == 4
    assert calls["n"] == 4
    # 首轮发出 4 个、其余 skipped；二轮 4 个端点探针预算为 0 而整批 skipped（同样未测量）。
    assert sorted(result.skipped_bearings) == [0, 45, 90, 135, 180, 225, 270, 315]
    assert result.failed_bearings == []
    assert not [w for w in result.warnings if w.startswith("ray_failed")]
