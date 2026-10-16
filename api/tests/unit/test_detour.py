# -*- coding: utf-8 -*-
from core.detour import free_detour, keep_route_detour


def test_free_detour_allows_negative_extra_and_enforces_budget():
    result = free_detour(600, 500, 1000, wait_seconds=60, service_seconds=300,
                         deadline_seconds=1460)
    assert result.feasible
    assert result.extra_travel_seconds == 100
    assert result.finish_seconds == 1460

    cheaper = free_detour(400, 500, 1000)
    assert cheaper.feasible
    assert cheaper.extra_travel_seconds == -100

    over_budget = free_detour(600, 500, 1000, max_extra_travel_seconds=50)
    assert not over_budget.feasible
    assert over_budget.reason == "EXTRA_BUDGET"
    late = free_detour(600, 500, 1000, deadline_seconds=1099)
    assert not late.feasible


def test_keep_route_enumerates_ordered_entry_and_return_only():
    result = keep_route_detour(
        prefix_seconds=[0, 300, 600, 1000],
        route_to_poi=[50, 20, 30, 80],
        poi_to_route=[40, 30, 20, 10],
        baseline_seconds=1000,
    )
    assert result.feasible
    assert result.best is not None
    assert result.best.entry_index <= result.best.return_index
    assert (result.best.entry_index, result.best.return_index) == (0, 3)
    assert result.best.extra_travel_seconds == -940


def test_keep_route_missing_measurement_is_not_best_but_other_ij_may_work():
    result = keep_route_detour(
        prefix_seconds=[0, 300], route_to_poi=[None, 20],
        poi_to_route=[30, None], baseline_seconds=1000,
    )
    assert not result.feasible
    assert result.reason == "NO_FEASIBLE_IJ"
