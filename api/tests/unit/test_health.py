# -*- coding: utf-8 -*-
def test_health_in_live_mode(live_settings):
    live_settings.os.environ["BAIDU_MAP_AK"] = "test-ak"
    from api.app.config import get_settings
    from api.app.main import app
    from fastapi.testclient import TestClient

    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["mode"] == "live"
            assert body["baiduConfigured"] is True
            assert body["features"]["liveApi"] is True
    finally:
        get_settings.cache_clear()


def test_root_points_to_docs(live_settings):
    live_settings.os.environ["BAIDU_MAP_AK"] = "test-ak"
    from api.app.config import get_settings
    from api.app.main import app
    from fastapi.testclient import TestClient

    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert resp.json()["health"] == "/api/health"
    finally:
        get_settings.cache_clear()
