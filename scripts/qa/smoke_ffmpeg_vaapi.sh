#!/usr/bin/env bash
set -euo pipefail

DEVICE="${1:-/dev/dri/renderD128}"

if [[ ! -e "$DEVICE" ]]; then
  echo "VA-API device not found at $DEVICE" >&2
  exit 1
fi

if command -v vainfo >/dev/null 2>&1; then
  echo "Running vainfo..."
  vainfo || true
fi

echo "Running ffmpeg VA-API smoke test..."
ffmpeg -hide_banner \
  -init_hw_device "vaapi=va:${DEVICE}" \
  -filter_hw_device va \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -t 3 \
  -vf "format=nv12,hwupload" \
  -c:v h264_vaapi \
  -f null -

echo "VA-API ffmpeg smoke test passed."
