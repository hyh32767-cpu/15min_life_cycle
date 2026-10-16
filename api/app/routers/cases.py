# -*- coding: utf-8 -*-
"""历史实验案例:只读 demo-data/v1/cases 下固化文件,不伪造数据。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from ..config import Settings
from ..dependencies import get_settings_dep
from ..models.api import CaseListResponse
from ..services.errors import ServiceError

router = APIRouter(tags=["cases"])


def _cases_dir(settings: Settings) -> Path:
    return Path(settings.data_dir) / "cases"


def _load_index(settings: Settings) -> dict:
    index_path = _cases_dir(settings) / "index.json"
    if not index_path.exists():
        raise ServiceError("CASE_NOT_FOUND", "案例索引缺失",
                           http_status=404,
                           details={"path": str(index_path)})
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServiceError("CASE_NOT_FOUND", "案例索引损坏",
                           http_status=404) from exc


def _summarize(entry: dict) -> dict:
    case_id = str(entry.get("caseId", ""))
    title = str(entry.get("title", case_id))
    region = title.split("·")[0] if "·" in title else title
    source_path = str(entry.get("sourcePath", ""))
    summary = f"来源 {source_path}" if source_path else "历史实验固化案例"
    center = dict(entry.get("centerWgs84") or {})
    files = [str(entry["file"])] if entry.get("file") else []
    return {
        "id": case_id,
        "title": title,
        "region": region,
        "summary": summary,
        "center": center,
        "files": files,
    }


@router.get("/api/cases", response_model=CaseListResponse)
def list_cases(settings: Settings = Depends(get_settings_dep)) -> CaseListResponse:
    index = _load_index(settings)
    entries = index.get("cases", [])
    if not isinstance(entries, list):
        raise ServiceError("CASE_NOT_FOUND", "案例索引格式错误",
                           http_status=404)
    return CaseListResponse(**{"cases": [_summarize(entry) for entry in entries
                                         if isinstance(entry, dict)]})


@router.get("/api/cases/{case_id}")
def get_case(case_id: str, settings: Settings = Depends(get_settings_dep)) -> dict:
    index = _load_index(settings)
    entries = index.get("cases", [])
    match = next((entry for entry in entries
                  if isinstance(entry, dict) and entry.get("caseId") == case_id),
                 None)
    if match is None or not match.get("file"):
        raise ServiceError("CASE_NOT_FOUND", f"案例不存在: {case_id}",
                           http_status=404)
    case_path = _cases_dir(settings) / str(match["file"])
    if not case_path.exists():
        raise ServiceError("CASE_NOT_FOUND", f"案例文件缺失: {case_id}",
                           http_status=404,
                           details={"path": str(case_path)})
    try:
        return json.loads(case_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServiceError("CASE_NOT_FOUND", f"案例文件损坏: {case_id}",
                           http_status=404) from exc
