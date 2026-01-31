#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

BACKEND_VENV="$ROOT/backend/.venv/bin/uvicorn"
if [[ -x "$BACKEND_VENV" ]]; then
  UVICORN="$BACKEND_VENV"
elif [[ -x "$ROOT/backend/venv/bin/uvicorn" ]]; then
  UVICORN="$ROOT/backend/venv/bin/uvicorn"
else
  UVICORN="uvicorn"
fi

( cd "$ROOT/backend" && "$UVICORN" main:app --host 0.0.0.0 --port 8000 > /tmp/mustarrd-backend.log 2>&1 & )
( cd "$ROOT/frontend" && npm run dev > /tmp/mustarrd-frontend.log 2>&1 & )

echo "Backend log: /tmp/mustarrd-backend.log"
echo "Frontend log: /tmp/mustarrd-frontend.log"
