# -*- coding: utf-8 -*-
"""纯 live 方向/矩阵响应归一化：内联百度响应体，不读 fixture 文件。"""

from core.travel import direction_body_to_leg, matrix_body_to_matrix


def _direction_body() -> dict:
    steps = [
        {"path": f"116.3{i},40.0{i};116.3{i + 1},40.0{i + 1}", "distance": 500,
         "duration": 450, "instructions": "步行"}
        for i in range(8)
    ]
    return {"status": 0, "result": {"routes": [{
        "duration": 3595, "distance": 3968,
        "originLocation": {"lat": 40.09, "lng": 116.36},
        "destinationLocation": {"lat": 40.07, "lng": 116.33},
        "steps": steps,
    }]}}


def _matrix_body() -> dict:
    return {"status": 0, "result": [
        {"duration": {"value": 0}, "distance": {"value": 0}},
        {"duration": {"value": 600}, "distance": {"value": 700}},
        {"duration": {"value": 620}, "distance": {"value": 720}},
        {"duration": {"value": 0}, "distance": {"value": 0}},
    ]}


def test_direction_body_to_leg_keeps_same_response_metrics():
    leg = direction_body_to_leg(_direction_body(), from_id="company", to_id="home")
    assert leg.ok
    assert leg.duration_s == 3595
    assert leg.distance_m == 3968
    assert len(leg.geometry) > 10
    assert leg.geometry[0]["crs"] == "BD09"


def test_matrix_body_to_directional_cells():
    matrix = matrix_body_to_matrix(_matrix_body(), origin_ids=["company", "home"],
                                   destination_ids=["company", "home"])
    assert len(matrix.cells) == 4
    assert matrix.complete
    assert matrix.get(0, 1).duration_s is not None
    assert matrix.get(1, 0).duration_s is not None
    assert matrix.get(0, 0).duration_s == 0


def test_missing_direction_or_matrix_items_are_not_zero():
    leg = direction_body_to_leg({"status": 0, "result": {"routes": []}}, from_id="a", to_id="b")
    assert leg.status == "no_route"
    assert leg.duration_s is None

    matrix = matrix_body_to_matrix({"status": 0, "result": []}, origin_ids=["a", "b"],
                                   destination_ids=["c", "d"])
    assert len(matrix.cells) == 4
    assert not matrix.complete
    assert all(cell.status == "error" and cell.duration_s is None for cell in matrix.cells)
