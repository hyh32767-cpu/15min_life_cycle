# -*- coding: utf-8 -*-
"""纯算法预检：坐标、采样、等时圈二分、失败语义与响应归一化。

运行:
    python3 tools/preflight/algorithm_checks.py

不需要网络，不会调用百度 API。
"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.baidu_client import ApiResult, matrix_items, place_detail_item  # noqa: E402
from core.coord import (bd09_to_wgs84, dest_at, gcj02_to_bd09, haversine,  # noqa: E402
                        wgs84_to_bd09, wgs84_to_gcj02)
from core.isochrone import bisect_ray, compute_isochrone_batched  # noqa: E402


class CoordTests(unittest.TestCase):
    def test_crs_roundtrip_is_sub_meter(self):
        # 北京天安门附近,单位:lng,lat
        lng, lat = 116.397128, 39.916527
        gcj = wgs84_to_gcj02(lng, lat)
        bd = gcj02_to_bd09(*gcj)
        back = bd09_to_wgs84(*bd)
        self.assertLess(haversine(lng, lat, *back), 1.0)

    def test_dest_at_matches_haversine(self):
        center_lng, center_lat = 116.310, 39.990
        for bearing in (0.0, 45.0, 90.0, 180.0, 270.0, 330.0):
            for distance in (200.0, 800.0, 1400.0, 2000.0):
                lat, lng = dest_at(center_lng, center_lat, bearing, distance)
                measured = haversine(center_lng, center_lat, lng, lat)
                self.assertLess(abs(measured - distance) / distance, 0.003,
                                f"bearing={bearing} distance={distance} measured={measured}")


class IsochronePureTests(unittest.TestCase):
    def test_bisect_success_recovers_true_radius(self):
        target_m = 800.0
        threshold_s = 900.0
        speed = threshold_s / target_m  # seconds per meter

        def measure_at(d):
            return d * speed

        result = bisect_ray(measure_at, threshold_s=threshold_s, tol_m=1.0)
        self.assertTrue(result.ok)
        self.assertAlmostEqual(result.radius_m, target_m, delta=1.0)
        self.assertTrue(all(p.duration_s is not None or p.status != "ok" for p in result.probes))

    def test_missing_initial_probe_fails_without_radius(self):
        result = bisect_ray(lambda _d: None, threshold_s=900.0)
        self.assertFalse(result.ok)
        self.assertIsNone(result.radius_m)
        self.assertEqual(result.status, "failed")
        self.assertIn("initial", result.reason)

    def test_missing_midpoint_does_not_fabricate_800m(self):
        target_m = 800.0
        threshold_s = 900.0
        speed = threshold_s / target_m

        def measure_at(d):
            # 800m 初始点可达; 800~900m 之间的首个中点缺测 -> 不得回退成 ±800m。
            if 800.0 < d < 900.0:
                return None
            return d * speed

        result = bisect_ray(measure_at, threshold_s=threshold_s, tol_m=1.0)
        self.assertFalse(result.ok)
        self.assertIsNone(result.radius_m)
        self.assertEqual(result.status, "failed")
        self.assertIn("bisect", result.reason)

    def test_threshold_beyond_hi_fails_closed(self):
        result = bisect_ray(lambda _d: 60.0, threshold_s=900.0)
        self.assertFalse(result.ok)
        self.assertIsNone(result.radius_m)
        self.assertIn("hi", result.reason)

    def test_threshold_below_lo_fails_closed(self):
        result = bisect_ray(lambda _d: 5000.0, threshold_s=900.0)
        self.assertFalse(result.ok)
        self.assertIsNone(result.radius_m)
        self.assertIn("lo", result.reason)

    def test_nonfinite_measurement_is_unknown(self):
        for value in (math.nan, math.inf, -1):
            result = bisect_ray(lambda _d: value, threshold_s=900)
            self.assertFalse(result.ok)
            self.assertIsNone(result.radius_m)

    def test_batch_budget_is_hard_limit(self):
        calls = []
        def measure(points):
            calls.extend(points)
            return [distance for _, distance in points]
        result = compute_isochrone_batched(measure, threshold_s=900,
            bearings=[0, 45, 90, 135, 180, 225, 270, 315], max_pairs=4)
        self.assertLessEqual(len(calls), 4)
        self.assertNotEqual(result.status, 'complete')


class ResponseNormalizationTests(unittest.TestCase):
    def test_matrix_items_maps_duration_and_distance(self):
        r = ApiResult(True, 0, "ok", {"result": [
            {"duration": {"value": 568}, "distance": {"value": 665}},
            {"duration": {"value": 0}, "distance": {"value": 0}},
        ]})
        self.assertEqual(matrix_items(r), [
            {"duration_s": 568, "distance_m": 665},
            {"duration_s": 0, "distance_m": 0},
        ])

    def test_place_detail_item_accepts_v3_results_and_v2_result(self):
        v3 = ApiResult(True, 0, "ok", {"results": [{"uid": "u1", "name": "v3"}]})
        v2 = ApiResult(True, 0, "ok", {"result": {"uid": "u1", "name": "v2"}})
        self.assertEqual(place_detail_item(v3)["name"], "v3")
        self.assertEqual(place_detail_item(v2)["name"], "v2")
        self.assertIsNone(place_detail_item(ApiResult(False, 4, "quota", {})))


if __name__ == "__main__":
    unittest.main(verbosity=2)
