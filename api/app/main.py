# -*- coding: utf-8 -*-
"""FastAPI 入口:健康检查、模式边界和统一错误结构。

M0 只提供可运行骨架;百度业务端点按 docs/19 §14 的语义在 M1 接入。
"""
from __future__ import annotations

import os
import logging
from starlette.exceptions import HTTPException as StarletteHTTPException

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import ConfigError, ROOT
from .dependencies import get_baidu_service
from .models.common import HealthResponse
from .routers import cases, community, explore, insights, isochrones, locations, maps, plans, pois, replan, routing
from .services.errors import ServiceError

app = FastAPI(
    title="顺路 · 15 分钟生活助手 API",
    version="0.1.0",
    description="百度真实空间数据 + 可标注模拟行为耗时 + 真实规划计算",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": {
        "code": "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR",
        "message": "请求的内容不存在" if exc.status_code == 404 else "请求未完成，请稍后重试",
        "retryable": False,
    }})


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # 不记录原始URL、异常正文或请求体，避免上游签名/密钥泄露。
    logging.getLogger(__name__).error("Unhandled API exception: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"error": {
        "code": "INTERNAL_ERROR", "message": "服务暂时无法完成查询，请稍后重试", "retryable": False,
    }})


@app.exception_handler(ConfigError)
async def config_error_handler(_request: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "CONFIG_ERROR", "message": str(exc)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    details = []
    for item in exc.errors():
        context = item.get("ctx") or {}
        details.append({
            "loc": list(item.get("loc") or []),
            "msg": str(item.get("msg", "")),
            "type": str(item.get("type", "")),
            **({"error": str(context["error"])} if "error" in context else {}),
        })
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求字段校验失败",
                "details": details,
            }
        },
    )


@app.exception_handler(ServiceError)
async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else {},
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "retryable": exc.retryable,
                "retryAfterSeconds": exc.retry_after,
            }
        },
    )


app.include_router(locations.router)
app.include_router(maps.router)
app.include_router(routing.router)
app.include_router(pois.router)
app.include_router(plans.router)
app.include_router(replan.router)
app.include_router(explore.router)
app.include_router(community.router)
app.include_router(insights.router)
app.include_router(cases.router)
app.include_router(isochrones.router)


@app.get("/", include_in_schema=False)
def root() -> dict:
    if os.environ.get("SHUNSHOU_SERVE_WEB") == "1":
        from fastapi.responses import FileResponse
        dist = ROOT / "web" / "dist"
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
    return {"service": "顺路 · 15 分钟生活助手 API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health", response_model=HealthResponse)
def health(service=Depends(get_baidu_service)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        mode="live",
        baiduConfigured=service.settings.baidu_configured,
        warnings=[],
        features={
            "liveApi": True,
        },
    )


@app.get("/api/ledger/summary")
def ledger_summary(group_by: str | None = None, service=Depends(get_baidu_service)) -> dict:
    """本次调用账本汇总：traceId/stage/接口/cacheHit/status/pairs。演示 T503 用。"""
    ledger = service.ledger
    result = ledger.summary(group_by=group_by) if group_by else ledger.summary()
    return {
        "rows": result.rows,
        "requests": result.requests,
        "liveRequests": result.live_requests,
        "cacheHits": result.cache_hits,
        "pairs": result.pairs,
        "errors": result.errors,
        **({"byStage": [item.as_dict() for item in result.by_stage]} if result.by_stage else {}),
        **({"byInterface": [item.as_dict() for item in result.by_interface]} if result.by_interface else {}),
        "note": "本次产品账本汇总（不含历史实验台账）；live 请求与 cache hit 分别计数",
    }


if os.environ.get("SHUNSHOU_SERVE_WEB") == "1":
    from .spa import SPAStaticFiles
    dist = ROOT / "web" / "dist"
    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="web")
