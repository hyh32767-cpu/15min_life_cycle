#!/usr/bin/env bash
set -e
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node 2>/dev/null | tail -n 1)/bin:$PATH"
echo "[1/2] Starting Backend API on http://127.0.0.1:18080 ..."
.venv/bin/python -m uvicorn api.app.main:app --host 127.0.0.1 --port 18080 --reload &
API_PID=$!
trap "kill $API_PID 2>/dev/null || true" EXIT
echo "[2/2] Starting Frontend Vite on http://127.0.0.1:5173 ..."
cd web && npm run dev -- --host 127.0.0.1 --port 5173
