# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_baidu_service
from ..models.api import LocationSearchResponse, LocationResolveRequest, LocationResolveResponse
from ..services.baidu_service import BaiduService

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("/search", response_model=LocationSearchResponse)
def search_locations(
    q: str = Query(..., min_length=1, description="地点或地址"),
    city: Optional[str] = Query(default=None, description="可选城市限定"),
    service: BaiduService = Depends(get_baidu_service),
) -> LocationSearchResponse:
    candidates, trace_id = service.search_locations(q, city=city)
    return LocationSearchResponse(
        traceId=trace_id,
        mode="live",
        candidates=candidates,
        warnings=[],
    )


@router.post("/resolve", response_model=LocationResolveResponse)
def resolve_location(
    body: LocationResolveRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> LocationResolveResponse:
    place, trace = service.resolve_location(body.coord)
    return LocationResolveResponse(traceId=trace, place=place)


@router.get("/poi/{uid}", response_model=LocationResolveResponse)
def poi_location(uid: str, service: BaiduService = Depends(get_baidu_service)) -> LocationResolveResponse:
    place, trace = service.place_detail(uid)
    return LocationResolveResponse(traceId=trace, place=place)
