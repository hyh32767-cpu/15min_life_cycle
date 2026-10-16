from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app.spa import SPAStaticFiles


def test_production_entry_mounts_build_inside_its_distribution_root(tmp_path, monkeypatch):
    import importlib
    from api.app import config, main

    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app">distribution app</div>')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(config, "ROOT", tmp_path)
            patch.setenv("SHUNSHOU_SERVE_WEB", "1")
            importlib.reload(main)
            with TestClient(main.app) as client:
                for route in ("/", "/community", "/explore", "/cases"):
                    assert client.get(route).text == '<div id="app">distribution app</div>'
                assert client.get("/api/health").status_code == 503
                assert client.get("/api/missing").status_code == 404
                assert client.get("/assets/missing.js").status_code == 404
    finally:
        importlib.reload(main)


def test_built_app_serves_deep_links_without_hiding_missing_api_or_assets(tmp_path):
    (tmp_path / "index.html").write_text("<h1>phone app</h1>")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True))
    with TestClient(app) as client:
        for route in ["/", "/community", "/cases", "/explore"]:
            assert client.get(route).text == "<h1>phone app</h1>"
        for route in ["/api/missing", "/assets/missing.js", "/not-a-page"]:
            assert client.get(route).status_code == 404
