# -*- coding: utf-8 -*-
"""跨接口基础模型:坐标、来源、时长和健康状态。

对应 docs/18 §6 与 docs/19 §1:百度空间事实和模拟行为必须可逐字段区分。
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

DurationSeconds = Annotated[float, Field(ge=0.0)]
PositiveSeconds = Annotated[float, Field(gt=0.0)]


class SourceKind(str, Enum):
    LIVE_API = "live-api"
    API_CACHE = "api-cache"
    SYNTHETIC_ASSUMPTION = "synthetic-assumption"
    USER_INPUT = "user-input"
    DERIVED = "derived"


class Crs(str, Enum):
    BD09 = "BD09"
    GCJ02 = "GCJ02"
    WGS84 = "WGS84"


class Coord(BaseModel):
    """具名坐标:百度请求/响应默认 BD09,不静默混系。"""

    model_config = ConfigDict(extra="forbid")

    lng: float = Field(..., ge=-180.0, le=180.0)
    lat: float = Field(..., ge=-90.0, le=90.0)
    crs: Crs = Crs.BD09


class Provenance(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    source_kind: SourceKind = Field(alias="sourceKind")
    parents: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["live"] = "live"
    baidu_configured: bool = Field(alias="baiduConfigured")
    warnings: List[str] = Field(default_factory=list)
    features: Dict[str, bool] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[object] = None
    retryable: bool = False
    retry_after_seconds: Optional[int] = Field(default=None, alias="retryAfterSeconds")


class ErrorResponse(BaseModel):
    error: ErrorDetail
