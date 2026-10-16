# -*- coding: utf-8 -*-
"""路线采样点与 POI 之间的双向接入证据。

调用方必须分别传 T(sample_i, p) 和 T(p, sample_j);本模块不假设对称,
也不用欧氏距离补缺失测值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence


@dataclass
class CorridorEvidence:
    threshold_seconds: float
    inbound_reachable_indices: List[int] = field(default_factory=list)
    outbound_reachable_indices: List[int] = field(default_factory=list)
    missing_inbound_indices: List[int] = field(default_factory=list)
    missing_outbound_indices: List[int] = field(default_factory=list)
    symmetric_assumed: bool = False

    @property
    def can_enter(self) -> bool:
        return bool(self.inbound_reachable_indices)

    @property
    def can_return(self) -> bool:
        return bool(self.outbound_reachable_indices)

    @property
    def directional_feasible(self) -> bool:
        return self.can_enter and self.can_return

    def as_dict(self) -> dict:
        return {
            "thresholdSeconds": self.threshold_seconds,
            "inboundReachableIndices": self.inbound_reachable_indices,
            "outboundReachableIndices": self.outbound_reachable_indices,
            "missingInboundIndices": self.missing_inbound_indices,
            "missingOutboundIndices": self.missing_outbound_indices,
            "symmetricAssumed": self.symmetric_assumed,
            "directionalFeasible": self.directional_feasible,
        }


def compute_corridor_evidence(*, threshold_seconds: float,
                              inbound_times: Sequence[Optional[float]],
                              outbound_times: Sequence[Optional[float]]) -> CorridorEvidence:
    evidence = CorridorEvidence(threshold_seconds=threshold_seconds)
    for index, value in enumerate(inbound_times):
        if value is None:
            evidence.missing_inbound_indices.append(index)
        elif value <= threshold_seconds:
            evidence.inbound_reachable_indices.append(index)
    for index, value in enumerate(outbound_times):
        if value is None:
            evidence.missing_outbound_indices.append(index)
        elif value <= threshold_seconds:
            evidence.outbound_reachable_indices.append(index)
    return evidence
