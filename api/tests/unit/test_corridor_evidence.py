# -*- coding: utf-8 -*-
from core.corridor_evidence import compute_corridor_evidence


def test_corridor_evidence_is_directional_and_never_fills_missing():
    evidence = compute_corridor_evidence(
        threshold_seconds=600,
        inbound_times=[900, 500, None, 450],
        outbound_times=[500, None, 300, 700],
    )
    assert evidence.can_enter
    assert evidence.can_return
    assert evidence.inbound_reachable_indices == [1, 3]
    assert evidence.outbound_reachable_indices == [0, 2]
    assert evidence.missing_inbound_indices == [2]
    assert evidence.missing_outbound_indices == [1]
    assert not evidence.symmetric_assumed
    assert evidence.directional_feasible


def test_one_direction_can_be_feasible_without_the_other():
    evidence = compute_corridor_evidence(
        threshold_seconds=600,
        inbound_times=[500, 550],
        outbound_times=[800, 900],
    )
    assert evidence.can_enter
    assert not evidence.can_return
    assert not evidence.directional_feasible
