# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_baidu_service
from ..models.api import (CorridorEvidenceRequest, CorridorEvidenceResponse,
                          CorridorRequest, CorridorResponse)
from ..services.baidu_service import BaiduService

router = APIRouter(tags=["pois"])


@router.post("/api/pois/corridor", response_model=CorridorResponse)
def corridor_pois(
    request: CorridorRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> CorridorResponse:
    result = service.corridor_pois(
        request.route_geometry,
        request.query_terms,
        category=request.category,
        corridor_buffer_m=request.corridor_buffer_m,
        window_radius_m=request.window_radius_m,
        window_spacing_m=request.window_spacing_m,
        max_pages_per_window=request.max_pages_per_window,
        max_unique=request.max_unique,
        detail_limit=request.detail_limit,
    )
    return CorridorResponse(**result)


@router.post("/api/pois/corridor/evidence", response_model=CorridorEvidenceResponse)
def corridor_evidence(
    request: CorridorEvidenceRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> CorridorEvidenceResponse:
    result = service.corridor_evidence(
        request.poi,
        request.route_geometry,
        baseline_duration_seconds=request.baseline_duration_seconds,
        threshold_seconds=request.threshold_seconds,
        sample_m=request.sample_m,
        max_samples=request.max_samples,
    )
    return CorridorEvidenceResponse(**result)
