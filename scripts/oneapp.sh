#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"

usage() {
  cat <<'EOF'
Usage:
  scripts/oneapp.sh install    # Install backend + frontend deps and build UI
  scripts/oneapp.sh build-ui   # Build frontend dist only
  scripts/oneapp.sh start      # Run unified app (UI + API) on :4177
EOF
}

resolve_backend_python() {
  if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    echo "$BACKEND_DIR/.venv/bin/python"
    return
  fi
  if [[ -x "$BACKEND_DIR/venv/bin/python" ]]; then
    echo "$BACKEND_DIR/venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  echo "python"
}

create_backend_venv_if_missing() {
  if [[ -x "$BACKEND_DIR/.venv/bin/python" || -x "$BACKEND_DIR/venv/bin/python" ]]; then
    return
  fi

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to create backend virtualenv."
    exit 1
  fi

  echo "Creating backend virtualenv at backend/.venv"
  python3 -m venv "$BACKEND_DIR/.venv"
}

install_backend_requirements() {
  create_backend_venv_if_missing
  local backend_python
  backend_python="$(resolve_backend_python)"
  echo "Installing backend requirements with $backend_python"
  "$backend_python" -m pip install -r "$BACKEND_DIR/requirements.txt"
}

install_frontend_requirements() {
  echo "Installing frontend dependencies"
  (cd "$FRONTEND_DIR" && npm ci)
}

build_frontend() {
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    install_frontend_requirements
  fi
  echo "Building frontend dist"
  (cd "$FRONTEND_DIR" && npm run build)
}

ensure_backend_ready() {
  local backend_python
  backend_python="$(resolve_backend_python)"
  if ! "$backend_python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "Backend dependencies are missing. Run: scripts/oneapp.sh install"
    exit 1
  fi
}

start_unified_app() {
  if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
    echo "Frontend dist is missing. Building it now."
    build_frontend
  fi

  ensure_backend_ready

  local backend_python
  backend_python="$(resolve_backend_python)"

  echo "Starting Mustarrd unified app on http://localhost:4177"
  export CATCHUP_FRONTEND_DIST="$FRONTEND_DIR/dist"
  cd "$BACKEND_DIR"
  exec "$backend_python" main.py
}

case "${1:-}" in
  install)
    install_backend_requirements
    install_frontend_requirements
    build_frontend
    echo "Install complete. Run: scripts/oneapp.sh start"
    ;;
  build-ui)
    build_frontend
    ;;
  start)
    start_unified_app
    ;;
  *)
    usage
    exit 1
    ;;
esac
