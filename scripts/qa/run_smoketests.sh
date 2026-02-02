#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
QA_DIR="${1:-$ROOT_DIR/data/qa}"

"$ROOT_DIR/scripts/qa/generate_sample.sh" "$QA_DIR"

VIDEO="$QA_DIR/sample_with_ads.mp4"
EDL="$QA_DIR/sample_with_ads.edl"

if [[ "${RUN_COMSKIP:-0}" == "1" ]]; then
  echo "Running comskip smoke test (EDL may or may not be generated)..."
  "$ROOT_DIR/scripts/qa/smoke_comskip.sh" "$VIDEO" "${COMSKIP_INI:-}"
fi

echo "Running CPU commercial removal smoke test..."
PYTHONPATH="$ROOT_DIR/backend" python "$ROOT_DIR/scripts/qa/post_process_smoke.py" \
  --input "$VIDEO" \
  --edl "$EDL" \
  --format mp4 \
  --hw-accel cpu

if [[ -e /dev/dri/renderD128 ]]; then
  echo "Running VA-API commercial removal smoke test..."
  PYTHONPATH="$ROOT_DIR/backend" python "$ROOT_DIR/scripts/qa/post_process_smoke.py" \
    --input "$VIDEO" \
    --edl "$EDL" \
    --format mp4 \
    --hw-accel vaapi
else
  echo "Skipping VA-API test; /dev/dri/renderD128 not present."
fi

echo "Smoke tests complete."
