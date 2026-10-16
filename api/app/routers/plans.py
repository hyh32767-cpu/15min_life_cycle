# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_planning_service
from ..models.api import PlanRequest, PlanResponse
from ..services.planning_service import PlanningService

router = APIRouter(tags=["plans"])


@router.post("/api/plans", response_model=PlanResponse)
def create_plan(
    request: PlanRequest,
    service: PlanningService = Depends(get_planning_service),
) -> PlanResponse:
    return PlanResponse(**service.plan(request))
