# -*- coding: utf-8 -*-
"""T110/UI-0：/api/maps/config 只下发浏览器端 AK，绝不含 Server AK/SK。"""
from fastapi.testclient import TestClient

from api.app.main import app


def test_maps_config_never_leaks_server_keys(hermetic_app):
    client, service = hermetic_app
    server_ak = service.settings.baidu_ak
    assert server_ak, "hermetic service 应带 fake Server AK"
    with client:
        resp = client.get("/api/maps/config")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"configured", "ak", "version", "note"}
        assert "baidu_sk" not in body and "server" not in str(body).lower()
        if body["configured"]:
            assert body["ak"] and body["ak"] != server_ak
