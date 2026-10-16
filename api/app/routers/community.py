# -*- coding: utf-8 -*-
"""社区体检覆盖:纯计算,不访问外部接口。

明确 no_route 才是不可达；未测/失败不判盲区；newFacilityId 存在时用同一 times
（含 newFacilityTimes）重算一次覆盖，得 delta。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from fastapi import APIRouter

from ..models.api import CoverageRequest, CoverageResponse, CoverageTimeRequest
from ..services.errors import ServiceError

router = APIRouter(tags=["community"])


def _compute_coverage(
    threshold_seconds: float,
    grid_ids: List[str],
    facility_ids: List[str],
    times: Iterable[CoverageTimeRequest],
) -> Tuple[Dict[str, bool], List[str]]:
    best: Dict[str, float] = {}
    known_pairs = set()
    for cell in times:
        if cell.from_grid not in grid_ids or cell.to_facility not in facility_ids:
            continue
        if cell.status == "no_route":
            known_pairs.add((cell.from_grid, cell.to_facility))
            continue
        if cell.status != "ok" or cell.duration_seconds is None:
            continue
        known_pairs.add((cell.from_grid, cell.to_facility))
        known = best.get(cell.from_grid)
        value = float(cell.duration_seconds)
        if known is None or value < known:
            best[cell.from_grid] = value
    coverage = {
        grid_id: (best.get(grid_id) is not None
                  and best[grid_id] <= float(threshold_seconds))
        for grid_id in grid_ids
    }
    for grid_id, covered in coverage.items():
        if not covered and any((grid_id, facility_id) not in known_pairs for facility_id in facility_ids):
            raise ServiceError("INCOMPLETE_COVERAGE", "部分采样点的步行路线尚未查明，不能判为未覆盖", http_status=422)
    blind = [grid_id for grid_id, covered in coverage.items() if not covered]
    return coverage, blind


@router.post("/api/community/coverage", response_model=CoverageResponse)
def check_coverage(request: CoverageRequest) -> CoverageResponse:
    all_times = list(request.times) + list(request.new_facility_times)
    coverage, blind = _compute_coverage(
        float(request.threshold_seconds),
        list(request.grid_ids),
        list(request.facility_ids),
        request.times,
    )
    payload: dict = {
        "coverage": coverage,
        "coveredCount": len(request.grid_ids) - len(blind),
        "totalGrids": len(request.grid_ids),
        "blindGrids": blind,
    }
    if request.new_facility_id:
        facilities_after = list(request.facility_ids) + [request.new_facility_id]
        coverage_after, _ = _compute_coverage(
            float(request.threshold_seconds),
            list(request.grid_ids),
            facilities_after,
            all_times,
        )
        covered_after = sum(1 for value in coverage_after.values() if value)
        payload["delta"] = {
            "before": len(request.grid_ids) - len(blind),
            "after": covered_after,
        }
    return CoverageResponse(**payload)
