#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="/tmp/mustarrd-dev.pids"
TOOL_ENV_SCRIPT="$ROOT/scripts/tool-env.sh"

BACKEND_VENV="$ROOT/backend/.venv/bin/uvicorn"
if [[ -x "$BACKEND_VENV" ]]; then
  UVICORN="$BACKEND_VENV"
elif [[ -x "$ROOT/backend/venv/bin/uvicorn" ]]; then
  UVICORN="$ROOT/backend/venv/bin/uvicorn"
else
  UVICORN="uvicorn"
fi

start_services() {
  if [[ -f "$TOOL_ENV_SCRIPT" ]]; then
    # shellcheck disable=SC1090
    source "$TOOL_ENV_SCRIPT"
    catchup_apply_terminal_tool_env "$ROOT"
  fi

  (
    cd "$ROOT/backend"
    exec "$UVICORN" main:app --host 0.0.0.0 --port 4177 > /tmp/mustarrd-backend.log 2>&1
  ) &
  BACKEND_PID=$!
  ( cd "$ROOT/frontend" && exec npm run dev > /tmp/mustarrd-frontend.log 2>&1 ) &
  FRONTEND_PID=$!
  printf "BACKEND_PID=%s\nFRONTEND_PID=%s\n" "$BACKEND_PID" "$FRONTEND_PID" > "$PID_FILE"
  echo "Backend log: /tmp/mustarrd-backend.log"
  echo "Frontend log: /tmp/mustarrd-frontend.log"
  echo "Backend URL: http://localhost:4177"
  echo "Frontend URL: http://localhost:4178"
  [[ -n "${CATCHUP_FFMPEG_PATH:-}" ]] && echo "ffmpeg: $CATCHUP_FFMPEG_PATH"
  [[ -n "${CATCHUP_FFPROBE_PATH:-}" ]] && echo "ffprobe: $CATCHUP_FFPROBE_PATH"
  [[ -n "${CATCHUP_COMSKIP_PATH:-}" ]] && echo "comskip: $CATCHUP_COMSKIP_PATH"
}

kill_services() {
  if [[ -f "$PID_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$PID_FILE"
    for pid in "${BACKEND_PID:-}" "${FRONTEND_PID:-}"; do
      if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
    done
    rm -f "$PID_FILE"
  fi
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
