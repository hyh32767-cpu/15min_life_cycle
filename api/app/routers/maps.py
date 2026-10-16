# -*- coding: utf-8 -*-
"""浏览器地图配置：只下发浏览器端 AK（百度 JSAPI 底图用）。

Server AK/SK 永不经此接口下发。浏览器端 AK 靠 Referer 白名单保护，
业务 POI/路线/矩阵/等时圈仍经本项目 /api 并纳入账本。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..dependencies import get_settings_dep

router = APIRouter(prefix="/api/maps", tags=["maps"])


@router.get("/config")
def maps_config(settings: Settings = Depends(get_settings_dep)) -> dict:
    browser_key = settings.maps_browser_ak.strip()
    return {
        "configured": bool(browser_key),
        "ak": browser_key,
        "version": "4.0",
        "note": "百度 JSAPI 4.0 底图专用；业务数据仍经本项目 /api 并纳入账本",
    }
