"""实验网格的预算、缺测、非单调与同源重建保障；不调用真实API。"""
import math

from experiments.e4_sampling.outside_in_grid import outside_in


def test_queries_stay_on_lattice_and_budget_and_do_not_repeat():
    calls = []
    def oracle(x, y):
        calls.append((x, y))
        return math.hypot(x, y) * 2 + 1
    result = outside_in(oracle, budget=150)
    assert len(calls) == len(set(calls)) == result['queryCount'] <= 150
    assert all(x % 50 == y % 50 == 0 and abs(x) <= 500 and abs(y) <= 500 for x,y in calls)
    assert (0,0) not in calls
    assert all(result['prediction'][p] == v for p,v in result['observed'].items() if v is not None)


def test_unknown_remains_unknown_not_a_zero_or_no_route():
    result = outside_in(lambda x,y: None if (x,y)==(200,0) else 500, budget=100)
    assert result['observed'][200,0] is None
    assert (200,0) not in result['prediction']
    assert any((x,y) not in result['prediction'] for x in (150,200,250) for y in (0,50))


def test_non_monotonic_gap_does_not_stop_at_outer_reachable_point():
    def oracle(x,y):
        return 1100 if 50 <= math.hypot(x,y) <= 100 else 700
    result = outside_in(oracle, half=200, budget=80, thresholds=(900,))
    assert result['prediction'][100,0] > 900
    assert result['prediction'][200,0] <= 900
    assert result['prediction'][0,0] == 0


def test_budget_exhaustion_exposes_unresolved_instead_of_fake_completion():
    result = outside_in(lambda x,y: math.hypot(x,y)*2+1, budget=100)
    assert result['queryCount'] <= 100
    assert result['budgetExhausted']
    assert result['unresolved']


def test_sentinel_finds_hidden_interior_hole_and_queries_are_deterministic():
    def oracle(x,y):
        return 1300 if (x-100)**2 + (y-100)**2 <= 50**2 else 650
    a = outside_in(oracle, half=200, budget=80, thresholds=(900,))
    b = outside_in(oracle, half=200, budget=80, thresholds=(900,))
    assert a == b
    assert a['prediction'][100,100] > 900
    assert a['prediction'][200,200] <= 900


def test_2km_window_100m_grid_rescales_coarse_seeds_and_never_queries_50m():
    calls = []
    def oracle(x,y):
        calls.append((x,y))
        return math.hypot(x,y)+1
    result = outside_in(oracle,half=1000,spacing=100,budget=300,thresholds=(900,))
    assert all(x%100 == y%100 == 0 for x,y in calls)
    coarse_queries = calls[:result['phases'][0]['newQueries']]
    assert (1000,1000) in coarse_queries and (800,800) in coarse_queries
    assert len(result['prediction'])==441
    assert len(calls)<=300
    assert max(abs(x) for x,y in calls)==1000
