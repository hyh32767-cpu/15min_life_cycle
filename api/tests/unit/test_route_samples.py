# -*- coding: utf-8 -*-
"""纯 live 路线采样：内联百度 direction 响应体，不读 fixture 文件。"""

from core.route_samples import sample_direction_body, sample_geometry


def _direction_body() -> dict:
    steps = [
        {"path": f"116.3{i},40.0{i};116.3{i + 1},40.0{i + 1}", "distance": 500,
         "duration": 450, "instructions": "步行"}
        for i in range(8)
    ]
    return {"status": 0, "result": {"routes": [{
        "duration": 3600, "distance": 4000,
        "originLocation": {"lat": 40.09, "lng": 116.36},
        "destinationLocation": {"lat": 40.07, "lng": 116.33},
        "steps": steps,
    }]}}


def test_sample_direction_body_prefix_is_monotone_and_ends_at_api_duration():
    samples = sample_direction_body(_direction_body(), sample_m=300.0)
    assert len(samples) >= 10
    assert samples[0].prefix_seconds == 0
    assert abs(samples[-1].prefix_seconds - 3600) < 2
    assert all(a.prefix_seconds <= b.prefix_seconds for a, b in zip(samples, samples[1:]))
    assert samples[0].crs == "BD09"
    assert samples[0].time_source_kind == "derived"


def test_no_route_returns_empty_samples():
    assert sample_direction_body({"status": 0, "result": {"routes": []}}) == []


def test_sample_geometry_derives_prefix_from_same_total_duration():
    geometry = [
        {"lng": 116.30, "lat": 39.90, "crs": "BD09"},
        {"lng": 116.31, "lat": 39.90, "crs": "BD09"},
    ]
    samples = sample_geometry(geometry, total_duration_s=600, sample_m=300)
    assert len(samples) >= 3
    assert samples[0].prefix_seconds == 0
    assert abs(samples[-1].prefix_seconds - 600) < 1e-6
    assert all(a.prefix_seconds <= b.prefix_seconds for a, b in zip(samples, samples[1:]))
    assert samples[0].source_kind == "api-cache"
    assert samples[0].time_source_kind == "derived"
