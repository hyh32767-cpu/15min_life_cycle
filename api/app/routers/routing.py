# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_baidu_service
from ..models.api import (TravelMatrixRequest, TravelMatrixResponse,
                          WalkingRouteRequest, WalkingRouteResponse)
from ..services.baidu_service import BaiduService

router = APIRouter(tags=["routing"])


@router.post("/api/routes/walking", response_model=WalkingRouteResponse)
def walking_route(
    request: WalkingRouteRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> WalkingRouteResponse:
    result = service.walking_route(request.origin, request.destination)
    return WalkingRouteResponse(**result)


@router.post("/api/travel-matrix", response_model=TravelMatrixResponse)
def travel_matrix(
    request: TravelMatrixRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> TravelMatrixResponse:
    result = service.travel_matrix(request.origins, request.destinations)
    return TravelMatrixResponse(**result)
