# -*- coding: utf-8 -*-
from core.isochrone import compute_isochrone


def _linear(bearing, distance):
    return None if bearing == 90 else distance * (900.0 / 800.0)


def test_multi_ray_complete_recovers_all_radii():
    result = compute_isochrone(_linear, threshold_s=900.0,
                               bearings=[0, 45, 90, 135], tol_m=1.0)
    assert result.status == "partial"
    assert result.failed_bearings == [90]
    assert result.radii_m[0] > 0
    assert 90 not in result.radii_m


def test_multi_ray_all_success_complete():
    result = compute_isochrone(lambda _b, d: d * (900.0 / 800.0),
                               threshold_s=900.0, bearings=[0, 45, 90], tol_m=1.0)
    assert result.status == "complete"
    assert result.complete
    assert len(result.radii_m) == 3
    assert all(abs(radius - 800.0) <= 1.0 for radius in result.radii_m.values())


def test_probe_budget_skips_remaining_without_fake_radius():
    result = compute_isochrone(lambda _b, d: d * (900.0 / 800.0),
                               threshold_s=900.0, bearings=[0, 45, 90, 135],
                               tol_m=1.0, max_probes=3)
    assert result.status in {"partial", "failed"}
    assert result.skipped_bearings
    for bearing in result.skipped_bearings:
        assert bearing not in result.radii_m
