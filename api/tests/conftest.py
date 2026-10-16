# -*- coding: utf-8 -*-
"""F68：默认测试 hermetic——无 AK、无网络。所有 HTTP 契约测试必须 override
生产依赖（FakeAdapter + 临时 DB），不得触碰真实 Settings/百度网络。"""
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_storage(monkeypatch, tmp_path):
    """配置/健康测试也只能创建临时产品数据库，避免污染工作区与发布包。"""
    from api.app import config, dependencies

    for name, filename in (("CACHE_DB", "cache.db"), ("LEDGER_DB", "ledger.db"),
                           ("DERIVED_DB", "derived.db")):
        monkeypatch.setenv(name, str(tmp_path / filename))
    monkeypatch.setenv("BAIDU_MAP_AK", "")
    monkeypatch.setenv("BAIDU_MAP_SK", "")
    monkeypatch.setenv('BAIDU_HTTP_TRANSPORT', 'system')
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "missing.env")
    caches = (config.get_settings, dependencies._production_baidu_service,
              dependencies._production_isochrone_service)
    for cache in caches:
        cache.cache_clear()
    yield
    for cache in caches:
        cache.cache_clear()


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """CI 默认测试不准外呼；FakeAdapter/原位 monkeypatch 不受影响。"""
    import socket
    def denied(*args, **kwargs):
        raise AssertionError("单元/契约测试禁止网络连接，请注入 FakeAdapter")
    monkeypatch.setattr(socket.socket, "connect", denied)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def live_settings(monkeypatch, tmp_path):
    """让 live 配置测试不读取仓库根 .env。"""
    from api.app import config

    fake_env = tmp_path / "missing.env"
    monkeypatch.setattr(config, "_ENV_FILE", fake_env)
    monkeypatch.delenv("BAIDU_MAP_AK", raising=False)
    monkeypatch.delenv("BAIDU_MAP_SK", raising=False)
    config.get_settings.cache_clear()
    yield config
    config.get_settings.cache_clear()


@pytest.fixture()
def hermetic_app(tmp_path):
    """F68：带 FakeAdapter 的 FastAPI app；override 生产依赖 + 临时 DB。

    连 `get_settings_dep` 一起 override：cases 等静态路由不触发真实 AK 校验。
    用法：`with hermetic_app[0]:`（fixture 直接 yield 已进入的 client 上下文）。
    """
    from fastapi.testclient import TestClient

    from api.app import dependencies
    from api.app.main import app
    from api.tests.unit.test_baidu_service import FakeAdapter, make_service

    service = make_service(tmp_path, FakeAdapter())
    app.dependency_overrides[dependencies.get_baidu_service] = lambda: service
    app.dependency_overrides[dependencies.get_isochrone_service] = (
        lambda: dependencies.IsochroneService(
            service,
            cache=dependencies.DerivedCache(str(tmp_path / "derived.db")),
        )
    )
    app.dependency_overrides[dependencies.get_settings_dep] = lambda: service.settings
    try:
        with TestClient(app) as client:
            yield client, service
    finally:
        app.dependency_overrides.clear()
