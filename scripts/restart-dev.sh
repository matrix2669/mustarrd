#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CATCHUP_FFMPEG_PATH="/opt/homebrew/bin/ffmpeg"

pkill -f "uvicorn main:app" 2>/dev/null || true
pkill -f "npm run dev" 2>/dev/null || true

( cd "$ROOT/backend" && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 > /tmp/catchup-backend.log 2>&1 & )
( cd "$ROOT/frontend" && npm run dev > /tmp/catchup-frontend.log 2>&1 & )

echo "Backend log: /tmp/catchup-backend.log"
echo "Frontend log: /tmp/catchup-frontend.log"
