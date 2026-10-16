PY := .venv/bin/python
PYTHON ?= python3.12
API_PORT ?= 18080

.PHONY: api-install api-run api-test preflight web-install web-dev web-check web-build web-e2e setup check demo release

api-install:
	uv venv .venv --python 3.12
	uv pip install -r api/requirements-dev.txt

api-run:
	$(PY) -m uvicorn api.app.main:app --reload --port $(API_PORT)

api-test:
	$(PY) -m pytest api/tests -q

preflight:
	python3 tools/preflight/algorithm_checks.py
	python3 tools/preflight/api_smoke.py

web-install:
	cd web && npm ci

web-dev:
	cd web && npm run dev

web-check:
	cd web && npm run typecheck && npm run lint && npm test

web-build:
	cd web && npm run build

web-e2e:
	cd web && npm run test:e2e

setup:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -r api/requirements-dev.txt
	cd web && npm ci
	cd web && npx playwright install chromium

check: api-test web-check web-build web-e2e
	$(PY) tools/preflight/algorithm_checks.py
	$(PY) tools/demo/scan_release.py

demo: web-build
	SHUNSHOU_SERVE_WEB=1 $(PY) -m uvicorn api.app.main:app --host 127.0.0.1 --port $(API_PORT)

release: web-build
	$(PY) -m tools.demo.build_release
