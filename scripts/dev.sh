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

start_services() {
  ( cd "$ROOT/backend" && "$UVICORN" main:app --host 0.0.0.0 --port 4177 > /tmp/mustarrd-backend.log 2>&1 & )
  ( cd "$ROOT/frontend" && npm run dev > /tmp/mustarrd-frontend.log 2>&1 & )
  echo "Backend log: /tmp/mustarrd-backend.log"
  echo "Frontend log: /tmp/mustarrd-frontend.log"
  echo "Backend URL: http://localhost:4177"
  echo "Frontend URL: http://localhost:4178"
}

kill_services() {
  pkill -f "uvicorn main:app" 2>/dev/null || true
  pkill -f "npm run dev" 2>/dev/null || true
}

restart_services() {
  kill_services
  start_services
}

case "${1:-}" in
  start)
    start_services
    exit 0
    ;;
  restart)
    restart_services
    exit 0
    ;;
  kill)
    kill_services
    exit 0
    ;;
esac

while true; do
  echo ""
  echo "Mustarrd Dev Console"
  echo "1) Start"
  echo "2) Restart"
  echo "3) Kill"
  echo "4) Exit"
  read -r -p "Select an option: " choice
  case "$choice" in
    1) start_services ;;
    2) restart_services ;;
    3) kill_services ;;
    4) exit 0 ;;
    *) echo "Invalid option." ;;
  esac
done
