from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_baidu_service, get_isochrone_service
from ..models.api import (
    IsochronePoisRequest,
    IsochronePoisResponse,
    IsochroneRequest,
    IsochroneResponse,
    RouteBandRequest,
    ReportExportRequest,
    ReportExportResponse,
)
from ..services.baidu_service import BaiduService
from ..services.isochrone_service import IsochroneService

router = APIRouter(tags=["isochrones"])


@router.post('/api/route-bands')
def create_route_band(request: RouteBandRequest,
                      service: IsochroneService = Depends(get_isochrone_service)) -> dict:
    from ..services.route_band_service import RouteBandService
    return RouteBandService(service).run(request)


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": message})


def _render_report(report_id: str, format: str, payload: Dict[str, Any]) -> str:
    """F57：脱敏导出。只含摘要/边界/来源/警告；AK、原始请求体永不进入导出。"""
    report = payload.get("report") or {}
    radii = payload.get("radiiM") or {}
    summary = {
        "reportId": report_id,
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "sourceKind": payload.get("sourceKind"),
        "origin": payload.get("origin"),
        "thresholdSeconds": payload.get("thresholdSeconds"),
        "algorithmVersion": report.get("algorithmVersion") or payload.get("algorithmVersion"),
        "upstreamResponseHashes": payload.get("upstreamResponseHashes", []),
        "radiiM": radii,
        "reconstruction": payload.get("reconstruction"),
        "frontier": payload.get("frontier"),
        "effectiveBearings": report.get("effectiveBearings"),
        "maxRadiusM": report.get("maxRadiusM"),
        "minRadiusM": report.get("minRadiusM"),
        "medianRadiusM": report.get("medianRadiusM"),
        "approxAreaM2": report.get("approxAreaM2"),
        "approxNote": report.get("approxNote"),
        "failedBearings": payload.get("failedBearings"),
        "skippedBearings": payload.get("skippedBearings"),
        "warnings": payload.get("warnings"),
    }
    if format == "json":
        return json.dumps(summary, ensure_ascii=False, indent=2)
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        if payload.get('frontier'):
            writer.writerow(['eastM','northM','durationSeconds','state'])
            for sample in payload['frontier']['samples']:
                writer.writerow([sample['x'],sample['y'],sample['seconds'],sample['state']])
            return buf.getvalue()
        writer.writerow(["bearing", "radiusM"])
        for bearing in sorted(radii, key=lambda b: float(b)):
            writer.writerow([bearing, radii[bearing]])
        return buf.getvalue()
    lines = [
        f"# 等时圈报告 {report_id}",
        f"- 状态：{summary['status']} / 来源 {summary['sourceKind']} / 模式 {summary['mode']}",
        f"- 起点：{summary['origin']}，阈值 {summary['thresholdSeconds']}s",
        f"- 算法版本：{summary['algorithmVersion']}；上游响应：{summary['upstreamResponseHashes']}",
        (f"- 边界：{summary['effectiveBearings']} 条射线，最大 {summary['maxRadiusM']}m，"
         f"面积约 {summary['approxAreaM2']}㎡（实测重建近似）"),
        f"- 失败：{summary['failedBearings']}；跳过（未测量）：{summary['skippedBearings']}",
        f"- 警告：{summary['warnings']}",
    ]
    reconstruction = payload.get('reconstruction')
    if reconstruction:
        lines.append(f"- 显示等值线：{reconstruction['method']}，{reconstruction['sampleCount']} 个有效探针。{reconstruction['note']}")
    return "\n".join(lines) + "\n"

@router.post("/api/isochrones", response_model=IsochroneResponse)
def create_isochrone(
    request: IsochroneRequest,
    service: IsochroneService = Depends(get_isochrone_service),
) -> IsochroneResponse:
    result = service.run(
        request.origin,
        threshold_seconds=request.threshold_seconds,
        place_id=request.place_id,
        bearings=request.bearings,
        lo_m=request.lo_m,
        hi_m=request.hi_m,
        initial_m=request.initial_m,
        tol_m=request.tol_m,
        max_pairs=request.max_pairs,
        l2_first=request.l2_first,
        allow_l2_fallback=request.allow_l2_fallback,
        adaptive=request.adaptive,
        frontier=request.frontier,
    )
    return IsochroneResponse(**result)


@router.get("/api/isochrones/{task_id}/status", response_model=IsochroneResponse)
def isochrone_task_status(
    task_id: str,
    service: IsochroneService = Depends(get_isochrone_service),
) -> IsochroneResponse:
    status_payload = service.get_task_status(task_id)
    if status_payload is None:
        raise _not_found(f"未知 taskId: {task_id}")
    return IsochroneResponse(**status_payload)


def _report_payload(service: IsochroneService, task_id: str) -> Dict[str, Any]:
    record = service.cache.get_by_task(task_id) if service.cache else None
    if record is not None:
        payload = dict(record.result)
        payload['upstreamResponseHashes'] = (record.dependencies or {}).get('upstreamResponseHashes', [])
        payload['cacheHit'] = True
        payload['warnings'] = (payload.get('warnings') or []) + ['derived-cache-hit:ledger-cost-0']
        return payload
    # 可选加密失败时保留实测圈但不写派生缓存；报告仍应与任务最终边界一致。
    payload = service.get_task_status(task_id)
    if (payload is not None and payload.get('status') == 'complete'
            and payload.get('backgroundStatus') == 'completed' and payload.get('report')):
        expires = payload.get('expiresAt')
        try:
            valid = expires is not None and datetime.fromisoformat(expires) > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            valid = False
        if valid:
            return {**payload, 'cacheHit': False}
    raise _not_found(f"未知或已过期 reportId/taskId: {task_id}")


# F57：报告重取。优先派生缓存，未缓存的已完成实测任务可读取当前进程快照。
# F68/F66：派生库取自注入的等时圈服务，保证测试与生产同库、可重取。
@router.get("/api/isochrones/{task_id}/report")
def isochrone_report(task_id: str,
                     service: IsochroneService = Depends(get_isochrone_service)) -> Dict[str, Any]:
    payload = _report_payload(service, task_id)
    return {
        "reportId": task_id,
        "mode": payload.get("mode"),
        "sourceKind": payload.get("sourceKind"),
        "origin": payload.get("origin"),
        "thresholdSeconds": payload.get("thresholdSeconds"),
        "status": payload.get("status"),
        "report": payload.get("report"),
        "radiiM": payload.get("radiiM"),
        "frontier": payload.get("frontier"),
        "reconstruction": payload.get("reconstruction"),
        "failedBearings": payload.get("failedBearings"),
        "skippedBearings": payload.get("skippedBearings"),
        "pairsUsed": 0,
        "cacheHit": payload.get('cacheHit', False),
        "warnings": payload.get("warnings") or [],
        "traceId": payload.get("traceId"),
    }


# F57：报告导出。只输出脱敏字段（摘要/边界/来源/警告），不含 AK 与原始请求体。
@router.post("/api/reports/export", response_model=ReportExportResponse)
def export_report(request: ReportExportRequest,
                  service: IsochroneService = Depends(get_isochrone_service)) -> ReportExportResponse:
    payload = _report_payload(service, request.report_id)
    content = _render_report(request.report_id, request.format, payload)
    return ReportExportResponse(reportId=request.report_id, format=request.format, content=content)

@router.post("/api/isochrones/pois", response_model=IsochronePoisResponse)
def isochrone_pois(
    request: IsochronePoisRequest,
    service: BaiduService = Depends(get_baidu_service),
) -> IsochronePoisResponse:
    # F57：圈内 POI 真实 API 闭环；可达判定走起点有向矩阵。
    result = service.isochrone_pois(
        request.origin,
        request.threshold_seconds,
        request.query_terms,
        radii_m=request.radii_m,
        search_radius_m=request.search_radius_m,
        max_pages_per_term=request.max_pages_per_term,
        max_unique=request.max_unique,
    )
    return IsochronePoisResponse(**result)
