# -*- coding: utf-8 -*-
"""HTTP 边界模型:只做请求/响应包装,领域算法不依赖 FastAPI。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Literal

from pydantic import ConfigDict, Field, model_validator

from .common import BaseModel, Coord
from .domain import PlaceRef


class LocationSearchResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    candidates: List[PlaceRef]
    warnings: List[str] = Field(default_factory=list)


class LocationResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coord: Coord


class LocationResolveResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    place: PlaceRef


class WalkingRouteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: Coord
    destination: Coord


class WalkingRouteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    source_kind: str = Field(alias="sourceKind")
    cache_hit: bool = Field(alias="cacheHit")
    route: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)


class TravelMatrixRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 服务层按 ≤50 对/批自动拆分（见 BaiduService.travel_matrix 双维拆批），
    # 模型层只做防滥用的总量上限。
    origins: List[Coord] = Field(..., min_length=1, max_length=120)
    destinations: List[Coord] = Field(..., min_length=1, max_length=120)


class TravelMatrixResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    source_kind: str = Field(alias="sourceKind")
    cache_hit: bool = Field(alias="cacheHit")
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")
    cells: List[Dict[str, Any]]
    warnings: List[str] = Field(default_factory=list)
    response_hashes: List[str] = Field(default_factory=list, alias="responseHashes")


class CorridorRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    route_geometry: List[Coord] = Field(..., alias="routeGeometry", min_length=2)
    query_terms: List[str] = Field(..., alias="queryTerms", min_length=1)
    category: str = ""
    corridor_buffer_m: float = Field(default=1500.0, alias="corridorBufferM", gt=0)
    window_radius_m: float = Field(default=1000.0, alias="windowRadiusM", gt=0)
    window_spacing_m: float = Field(default=0.0, alias="windowSpacingM", ge=0)
    max_pages_per_window: int = Field(default=3, alias="maxPagesPerWindow", ge=1, le=10)
    max_unique: int = Field(default=100, alias="maxUnique", ge=1, le=500)
    detail_limit: int = Field(default=0, alias="detailLimit", ge=0, le=50)


class CorridorResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    source_kind: str = Field(alias="sourceKind")
    cache_hit: bool = Field(default=False, alias="cacheHit")
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")
    retrieval: Dict[str, Any]
    pois: List[Dict[str, Any]]
    warnings: List[str] = Field(default_factory=list)


class CorridorEvidenceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    place_id: str | None = Field(default=None, alias="placeId")
    poi: Coord
    route_geometry: List[Coord] = Field(..., alias="routeGeometry", min_length=2)
    baseline_duration_seconds: float = Field(..., alias="baselineDurationSeconds", gt=0)
    threshold_seconds: float = Field(..., alias="thresholdSeconds", gt=0)
    sample_m: float = Field(default=200.0, alias="sampleM", gt=0)
    max_samples: int = Field(default=12, alias="maxSamples", ge=2, le=50)


class CorridorEvidenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    source_kind: str = Field(alias="sourceKind")
    threshold_seconds: float = Field(alias="thresholdSeconds")
    pairs_used: int = Field(alias="pairsUsed")
    samples: List[Dict[str, Any]]
    evidence: Dict[str, Any]
    best_access: Dict[str, Any] | None = Field(default=None, alias="bestAccess")
    warnings: List[str] = Field(default_factory=list)


# F57：圈内 POI：按等时圈中心+外接半径做区域召回，再用起点->POI 有向矩阵过滤。
class IsochronePoisRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    origin: Coord
    threshold_seconds: float = Field(alias="thresholdSeconds", gt=0)
    query_terms: List[str] = Field(..., alias="queryTerms", min_length=1)
    radii_m: Dict[str, float] | None = Field(default=None, alias="radiiM")
    search_radius_m: float | None = Field(default=None, alias="searchRadiusM", gt=0)
    max_pages_per_term: int = Field(default=2, alias="maxPagesPerTerm", ge=1, le=5)
    max_unique: int = Field(default=50, alias="maxUnique", ge=1, le=200)


class IsochronePoisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trace_id: str = Field(alias="traceId")
    mode: str
    source_kind: str = Field(alias="sourceKind")
    reachable: List[Dict[str, Any]]
    unreachable: List[Dict[str, Any]]
    pairs_used: int = Field(alias="pairsUsed")
    retrieval: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)


# F57：报告重取与导出。报告由服务端派生缓存/本次结果重建；导出只给脱敏字段，不含 AK 与原始请求体。
class ReportExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    report_id: str = Field(alias="reportId", min_length=1)
    format: str = Field(default="md", pattern="^(md|json|csv)$")


class ReportExportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    report_id: str = Field(alias="reportId")
    format: str
    content: str
    warnings: List[str] = Field(default_factory=list)


class PlanWindowRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    opens_seconds: int = Field(alias="opensSeconds", ge=0)
    closes_seconds: int = Field(alias="closesSeconds", ge=0)


class PlanOptionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    place_id: str = Field(alias="placeId", min_length=1)
    service_seconds: int = Field(default=0, alias="serviceSeconds", ge=0)
    service_source_kind: str = Field(default="user-input", alias="serviceSourceKind")
    window_source_kind: str = Field(default="unknown", alias="windowSourceKind")
    window: PlanWindowRequest | None = None
    windows: List[PlanWindowRequest] | None = None


class PlanTaskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(..., min_length=1)
    options: List[PlanOptionRequest] = Field(..., min_length=1, max_length=3)
    required: bool = True
    precedence_ids: List[str] = Field(default_factory=list, alias="precedenceIds")


class TravelTimeRequest(BaseModel):
    """T212：status 三态（ok=有百度时长/no_route=百度明确无路/error=缺测或上游失败）。

    error 与 no_route 在规划层面都判不可行，但 infeasibleReasons 保留区分
    （OD_UNAVAILABLE vs NO_ROUTE），suggestions 人话不同；不静默合并。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    from_id: str = Field(alias="from", min_length=1)
    to_id: str = Field(alias="to", min_length=1)
    duration_seconds: float | None = Field(default=None, alias="durationSeconds", ge=0)
    distance_m: float | None = Field(default=None, alias="distanceM", ge=0)
    status: str = "ok"
    source_kind: str = Field(default="api-cache", alias="sourceKind")


class PlanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    start_id: str = Field(alias="startId", min_length=1)
    end_id: str = Field(alias="endId", min_length=1)
    departure_seconds: float = Field(alias="departureSeconds", ge=0)
    deadline_seconds: float = Field(alias="deadlineSeconds", ge=0)
    tasks: List[PlanTaskRequest] = Field(..., min_length=1, max_length=5)
    travel_times: List[TravelTimeRequest] = Field(..., alias="travelTimes", min_length=1)
    preference: str = "fastest"
    max_alternatives: int = Field(default=3, alias="maxAlternatives", ge=1, le=10)


class PlanStopResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    place_id: str = Field(alias="placeId")
    arrival_seconds: float = Field(alias="arrivalSeconds")
    start_seconds: float = Field(alias="startSeconds")
    finish_seconds: float = Field(alias="finishSeconds")
    wait_seconds: float = Field(alias="waitSeconds")
    travel_seconds: float = Field(alias="travelSeconds")
    travel_source_kind: str = Field(alias="travelSourceKind")
    service_source_kind: str = Field(alias="serviceSourceKind")
    window_source_kind: str = Field(alias="windowSourceKind")


class PlanAlternativeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    stops: List[PlanStopResponse]
    timeline: List[Dict[str, Any]]
    departure_seconds: float = Field(alias="departureSeconds")
    finish_seconds: float = Field(alias="finishSeconds")
    deadline_seconds: float = Field(alias="deadlineSeconds")
    slack_seconds: float = Field(alias="slackSeconds")
    total_travel_seconds: float = Field(alias="totalTravelSeconds")
    total_wait_seconds: float = Field(alias="totalWaitSeconds")
    total_service_seconds: float = Field(alias="totalServiceSeconds")
    total_walking_m: float = Field(alias="totalWalkingM")
    return_travel_seconds: float = Field(alias="returnTravelSeconds")
    return_travel_source_kind: str = Field(alias="returnTravelSourceKind")


class PlanResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    status: str
    alternatives: List[PlanAlternativeResponse]
    infeasible_reasons: Dict[str, int] = Field(alias="infeasibleReasons")
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)

class IsochroneRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    place_id: str | None = Field(default=None, alias="placeId")
    origin: Coord
    threshold_seconds: float = Field(alias="thresholdSeconds", gt=0)
    bearings: List[float] | None = None
    lo_m: float = Field(default=200.0, alias="loM", gt=0)
    hi_m: float = Field(default=1400.0, alias="hiM", gt=0)
    initial_m: float = Field(default=800.0, alias="initialM", gt=0)
    tol_m: float = Field(default=50.0, alias="tolM", gt=0)
    max_pairs: int = Field(default=64, alias="maxPairs", ge=1, le=2000)
    l2_first: bool = Field(default=False, alias="l2First")
    allow_l2_fallback: bool = Field(default=False, alias="allowL2Fallback")
    adaptive: bool = False
    frontier: bool = False

    @model_validator(mode="after")
    def check_ranges(self) -> "IsochroneRequest":
        import math
        if self.bearings is not None and (
            not self.bearings or len(self.bearings) > 360
            or len(set(self.bearings)) != len(self.bearings)
            or any(not math.isfinite(b) or not 0 <= b < 360 for b in self.bearings)
        ):
            raise ValueError("bearings 必须为非空、无重复的 [0, 360) 方向")
        if not self.hi_m > self.lo_m:
            raise ValueError("hiM 必须大于 loM")
        if not self.lo_m <= self.initial_m <= self.hi_m:
            raise ValueError("initialM 必须落在 [loM, hiM] 内")
        if not self.tol_m < (self.hi_m - self.lo_m):
            raise ValueError("tolM 必须小于 hiM - loM")
        return self


class RouteBandRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    route_geometry: List[Coord] = Field(alias='routeGeometry', min_length=2, max_length=10000)
    threshold_seconds: Literal[300, 600, 900, 1200] = Field(default=900, alias='thresholdSeconds')
    max_centers: int = Field(default=5, alias='maxCenters', ge=2, le=5)
    max_pairs: int = Field(default=1880, alias='maxPairs', ge=40, le=1880)
    cache_only: bool = Field(default=True, alias='cacheOnly')
    center_index: int | None = Field(default=None, alias='centerIndex', ge=0, le=4)
    task_ids: Dict[int, str] = Field(default_factory=dict, alias='taskIds', max_length=5)

    @model_validator(mode='after')
    def selected_live_center(self):
        if not self.cache_only and self.center_index is None:
            raise ValueError('补测必须指定一个采样位置')
        return self


class IsochroneResponse(BaseModel):
    frontier: Dict[str, Any] | None = None
    reconstruction: Dict[str, Any] | None = None
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    status: str
    place_id: str | None = Field(default=None, alias="placeId")
    threshold_seconds: float = Field(alias="thresholdSeconds")
    radii_m: Dict[str, float] = Field(alias="radiiM")
    failed_bearings: List[float] = Field(alias="failedBearings")
    skipped_bearings: List[float] = Field(alias="skippedBearings")
    algorithm_version: str = Field(alias="algorithmVersion")
    warnings: List[str] = Field(default_factory=list)
    cache_hit: bool = Field(default=False, alias="cacheHit")
    pairs_used: int = Field(default=0, alias="pairsUsed")
    trace_id: str | None = Field(default=None, alias="traceId")
    # F56：报告与来源展示所需；全部由服务端已有值派生，不新增外部调用。
    mode: str = Field(default="live")
    source_kind: str = Field(default="derived", alias="sourceKind")
    origin: Coord | None = None
    report: Dict[str, Any] = Field(default_factory=dict)
    background_status: str | None = Field(default=None, alias="backgroundStatus")


class ReplanEventRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    target_id: str = Field(alias="targetId", min_length=1)
    delay_seconds: float = Field(default=0.0, alias="delaySeconds", ge=0)


class ReplanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    tasks: List[PlanTaskRequest] = Field(..., min_length=1, max_length=5)
    completed_task_ids: List[str] = Field(default_factory=list, alias="completedTaskIds")
    current_node_id: str = Field(alias="currentNodeId", min_length=1)
    end_id: str = Field(alias="endId", min_length=1)
    current_time_seconds: float = Field(alias="currentTimeSeconds", ge=0)
    deadline_seconds: float = Field(alias="deadlineSeconds", ge=0)
    travel_times: List[TravelTimeRequest] = Field(..., alias="travelTimes", min_length=1)
    events: List[ReplanEventRequest] = Field(default_factory=list)
    preference: str = "fastest"


class ExploreCandidateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    place_id: str = Field(alias="placeId", min_length=1)
    place_name: Optional[str] = Field(default=None, alias="placeName")


class ExploreLegRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    candidate_id: str = Field(alias="candidateId", min_length=1)
    duration_seconds_start: Optional[float] = Field(default=None, alias="durationSecondsStart", ge=0)
    duration_seconds_return: Optional[float] = Field(default=None, alias="durationSecondsReturn", ge=0)
    status_start: str = Field(default="ok", alias="statusStart")
    status_return: str = Field(default="ok", alias="statusReturn")
    source_kind: str = Field(default="api-cache", alias="sourceKind")


class ExploreCheckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    budget_seconds: float = Field(alias="budgetSeconds", ge=0)
    service_seconds: float = Field(alias="serviceSeconds", ge=0)
    wait_seconds: float = Field(alias="waitSeconds", ge=0)
    candidates: List[ExploreCandidateRequest] = Field(..., min_length=1)
    legs: List[ExploreLegRequest] = Field(..., min_length=1)


class ExploreCheckItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    place_id: str = Field(alias="placeId")
    feasible: bool
    total_seconds: Optional[float] = Field(default=None, alias="totalSeconds")
    reason: str = ""


class ExploreCheckResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    results: List[ExploreCheckItem] = Field(default_factory=list)


class CoverageTimeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    from_grid: str = Field(alias="fromGrid", min_length=1)
    to_facility: str = Field(alias="toFacility", min_length=1)
    duration_seconds: Optional[float] = Field(default=None, alias="durationSeconds", ge=0)
    status: str = "ok"


class CoverageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    threshold_seconds: float = Field(alias="thresholdSeconds", gt=0)
    grid_ids: List[str] = Field(alias="gridIds", min_length=1)
    facility_ids: List[str] = Field(alias="facilityIds")
    times: List[CoverageTimeRequest] = Field(default_factory=list)
    new_facility_id: Optional[str] = Field(default=None, alias="newFacilityId")
    new_facility_times: List[CoverageTimeRequest] = Field(default_factory=list, alias="newFacilityTimes")

    @model_validator(mode="after")
    def unique_ids(self) -> "CoverageRequest":
        if len(set(self.grid_ids)) != len(self.grid_ids) or len(set(self.facility_ids)) != len(self.facility_ids):
            raise ValueError("采样点及设施 id 不能重复")
        if self.new_facility_id in self.facility_ids:
            raise ValueError("新增设施不能与已有设施重复")
        return self


class CoverageDelta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    before: int
    after: int


class CoverageResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    coverage: Dict[str, bool] = Field(default_factory=dict)
    covered_count: int = Field(alias="coveredCount")
    total_grids: int = Field(alias="totalGrids")
    blind_grids: List[str] = Field(default_factory=list, alias="blindGrids")
    delta: Optional[CoverageDelta] = None


class CaseSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    title: str
    region: str = ""
    summary: str = ""
    center: Dict[str, Any] = Field(default_factory=dict)
    files: List[str] = Field(default_factory=list)


class CaseListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    cases: List[CaseSummary] = Field(default_factory=list)
