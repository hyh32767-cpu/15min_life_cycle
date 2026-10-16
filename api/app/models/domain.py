# -*- coding: utf-8 -*-
"""产品领域 schema:M0 先覆盖位置、假设、任务、矩阵项和事件。

这些模型是 M1/M2 服务接口的公共契约;字段来源必须显式,负时长和
未知来源在入口即被拒绝。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import Coord, DurationSeconds, SourceKind


class PlaceRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    uid: Optional[str] = None
    name: str = Field(..., min_length=1)
    address: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    coord: Coord
    navi_coord: Optional[Coord] = Field(default=None, alias="naviCoord")
    source: SourceKind
    fetched_at: Optional[datetime] = Field(default=None, alias="fetchedAt")
    shop_hours: Optional[str] = Field(default=None, alias="shopHours")
    structured_hours: Optional[List[dict]] = Field(default=None, alias="structuredHours")
    status: Optional[str] = None
    detail_fetched_at: Optional[datetime] = Field(default=None, alias="detailFetchedAt")


class Assumption(BaseModel):
    """允许模拟的行为字段:必须逐字段标注 synthetic-assumption。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    target_id: str = Field(..., alias="targetId", min_length=1)
    field: str = Field(..., min_length=1)
    value: float
    seed: int
    reason: str = Field(..., min_length=1)
    source_kind: SourceKind = Field(..., alias="sourceKind")

    @field_validator("source_kind")
    @classmethod
    def must_be_synthetic(cls, value: SourceKind) -> SourceKind:
        if value != SourceKind.SYNTHETIC_ASSUMPTION:
            raise ValueError("Assumption.sourceKind 只能是 synthetic-assumption")
        return value


class TaskSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(..., min_length=1)
    kind: Literal["fixed", "category"]
    fixed_place_id: Optional[str] = Field(default=None, alias="fixedPlaceId")
    category: Optional[str] = None
    candidate_ids: List[str] = Field(default_factory=list, alias="candidateIds")
    service_seconds: DurationSeconds = Field(default=0, alias="serviceSeconds")
    required: bool = True
    precedence_ids: List[str] = Field(default_factory=list, alias="precedenceIds")

    @model_validator(mode="after")
    def check_kind_fields(self) -> "TaskSpec":
        if self.kind == "fixed" and not self.fixed_place_id:
            raise ValueError("fixed 任务必须提供 fixedPlaceId")
        if self.kind == "category" and not self.category:
            raise ValueError("category 任务必须提供 category")
        if self.id in self.precedence_ids:
            raise ValueError("任务不能依赖自身")
        return self


class TravelMatrixCell(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_place_id: str = Field(..., alias="from", min_length=1)
    to_place_id: str = Field(..., alias="to", min_length=1)
    duration_seconds: DurationSeconds = Field(..., alias="durationSeconds")
    distance_m: DurationSeconds = Field(..., alias="distanceM")
    status: Literal["ok", "no_route", "error"]
    source_kind: SourceKind = Field(..., alias="sourceKind")


class ScenarioEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(..., min_length=1)
    scenario_time_seconds: DurationSeconds = Field(..., alias="scenarioTimeSeconds")
    type: str = Field(..., min_length=1)
    target_id: str = Field(..., alias="targetId", min_length=1)
    payload: dict = Field(default_factory=dict)
    source_kind: SourceKind = Field(..., alias="sourceKind")


class CommuteRequest(BaseModel):
    """公司→家沿途检索/绕行筛选的输入边界。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    start: PlaceRef
    end: PlaceRef
    departure_at: datetime = Field(..., alias="departureAt")
    deadline_at: datetime = Field(..., alias="deadlineAt")
    category: str = Field(..., min_length=1)
    isochrone_seconds: DurationSeconds = Field(..., alias="isochroneSeconds")
    max_extra_travel_seconds: DurationSeconds = Field(..., alias="maxExtraTravelSeconds")
    service_seconds: DurationSeconds = Field(..., alias="serviceSeconds")
    route_policy: Literal["free", "keep-route"] = Field(..., alias="routePolicy")

    @model_validator(mode="after")
    def deadline_after_departure(self) -> "CommuteRequest":
        if self.deadline_at <= self.departure_at:
            raise ValueError("deadlineAt 必须晚于 departureAt")
        return self


class PoiOption(BaseModel):
    """候选 POI 的沿途成本与可行性;来源继承各 leg。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    place_uid: str = Field(..., alias="placeUid", min_length=1)
    place_name: str = Field(..., alias="placeName", min_length=1)
    extra_travel_seconds: DurationSeconds = Field(..., alias="extraTravelSeconds")
    wait_seconds: DurationSeconds = Field(..., alias="waitSeconds")
    service_seconds: DurationSeconds = Field(..., alias="serviceSeconds")
    home_arrival_at: datetime = Field(..., alias="homeArrivalAt")
    feasible: bool
    reasons: List[str] = Field(default_factory=list)


class RouteLeg(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_place_id: str = Field(..., alias="from", min_length=1)
    to_place_id: str = Field(..., alias="to", min_length=1)
    travel_seconds: DurationSeconds = Field(..., alias="travelSeconds")
    walking_m: DurationSeconds = Field(..., alias="walkingM")
    route_ref: Optional[str] = Field(default=None, alias="routeRef")
    source_kind: SourceKind = Field(..., alias="sourceKind")


class CorridorResult(BaseModel):
    """沿基准路线召回与筛选的响应骨架。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_hash: str = Field(..., alias="requestHash", min_length=1)
    baseline_route_ref: str = Field(..., alias="baselineRouteRef", min_length=1)
    poi_options: List[PoiOption] = Field(default_factory=list, alias="poiOptions")
    retrieval: dict = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class IsochroneResult(BaseModel):
    """等时圈任务结果状态;半径缺失时不允许伪造闭合多边形。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    place_uid: str = Field(..., alias="placeUid", min_length=1)
    threshold_seconds: DurationSeconds = Field(..., alias="thresholdSeconds")
    status: Literal["complete", "partial", "degraded", "failed"]
    geometry: Optional[dict] = None
    algorithm_version: str = Field(..., alias="algorithmVersion", min_length=1)
    source_kind: SourceKind = Field(..., alias="sourceKind")
    warnings: List[str] = Field(default_factory=list)
