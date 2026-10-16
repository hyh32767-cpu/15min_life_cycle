# -*- coding: utf-8 -*-
"""时间空档探索:纯计算,不访问外部接口。

任一段缺路判 infeasible NO_ROUTE；total=start+wait+service+return；
feasible=total<=budget。营业校验由前端完成。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..models.api import ExploreCheckRequest, ExploreCheckResponse

router = APIRouter(tags=["explore"])


@router.post("/api/explore/check", response_model=ExploreCheckResponse)
def check_explore(request: ExploreCheckRequest) -> ExploreCheckResponse:
    legs = {leg.candidate_id: leg for leg in request.legs}
    results = []
    for candidate in request.candidates:
        leg = legs.get(candidate.place_id)
        if (
            leg is None
            or leg.status_start != "ok"
            or leg.status_return != "ok"
            or leg.duration_seconds_start is None
            or leg.duration_seconds_return is None
        ):
            results.append({
                "placeId": candidate.place_id,
                "feasible": False,
                "totalSeconds": None,
                "reason": "NO_ROUTE",
            })
            continue
        total = (float(leg.duration_seconds_start)
                 + float(request.wait_seconds)
                 + float(request.service_seconds)
                 + float(leg.duration_seconds_return))
        if total <= float(request.budget_seconds):
            results.append({
                "placeId": candidate.place_id,
                "feasible": True,
                "totalSeconds": total,
                "reason": "",
            })
        else:
            results.append({
                "placeId": candidate.place_id,
                "feasible": False,
                "totalSeconds": total,
                "reason": "OVER_BUDGET",
            })
    return ExploreCheckResponse(**{"results": results})
