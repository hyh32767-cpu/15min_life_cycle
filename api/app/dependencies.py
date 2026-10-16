# -*- coding: utf-8 -*-
"""FastAPI 依赖注入。

F68：`get_settings`/`get_baidu_service`/`get_isochrone_service` 均经 FastAPI
Depends 注入，可被测试 override；默认实现走 lru_cache 的生产单例。
直接调用函数名（不经 Depends）仍返回生产单例，供 ledger 等内部调用。
"""
from __future__ import annotations

from functools import lru_cache

from .config import ROOT, Settings, get_settings
from .services.baidu_service import BaiduService
from .services.isochrone_service import IsochroneService
from .services.planning_service import PlanningService
from .storage.derived_cache import DerivedCache


@lru_cache(maxsize=1)
def _production_baidu_service() -> BaiduService:
    return BaiduService(get_settings())


@lru_cache(maxsize=1)
def _production_isochrone_service() -> IsochroneService:
    settings = get_settings()
    derived_db = settings.derived_db or str(ROOT / "api" / "var" / "derived.db")
    return IsochroneService(_production_baidu_service(), cache=DerivedCache(derived_db))


def get_settings_dep() -> Settings:
    return get_settings()


def get_baidu_service() -> BaiduService:
    return _production_baidu_service()


def get_planning_service() -> PlanningService:
    return PlanningService()


def get_isochrone_service() -> IsochroneService:
    return _production_isochrone_service()
