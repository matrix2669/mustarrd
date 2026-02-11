#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
BUILD_DIR="${REPO_ROOT}/desktop-electron/.backend-build"
OUTPUT_DIR="${REPO_ROOT}/desktop-electron/backend-bin"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
mkdir -p "${OUTPUT_DIR}"

python3 -m venv "${BUILD_DIR}/venv"
source "${BUILD_DIR}/venv/bin/activate"

pip install --upgrade pip
pip install -r "${BACKEND_DIR}/requirements.txt" pyinstaller

pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name catchup-backend \
  --distpath "${BUILD_DIR}/dist" \
  --workpath "${BUILD_DIR}/work" \
  --specpath "${BUILD_DIR}" \
  --paths "${BACKEND_DIR}" \
  "${BACKEND_DIR}/desktop_server.py"

cp "${BUILD_DIR}/dist/catchup-backend" "${OUTPUT_DIR}/catchup-backend"
chmod +x "${OUTPUT_DIR}/catchup-backend"

echo "Backend binary written to ${OUTPUT_DIR}/catchup-backend"
