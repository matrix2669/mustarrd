#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-./data/qa}"
mkdir -p "$OUT_DIR"

VIDEO="$OUT_DIR/sample_with_ads.mp4"
EDL="$OUT_DIR/sample_with_ads.edl"

if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -hide_banner -y \
    -f lavfi -i "testsrc2=size=1280x720:rate=30" \
    -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
    -t 60 \
    -c:v libx264 -pix_fmt yuv420p \
    -c:a aac -b:a 128k \
    "$VIDEO"
else
  echo "ffmpeg not found in PATH." >&2
  exit 1
fi

cat > "$EDL" <<EOF
5.0 12.0 0
30.0 38.0 0
EOF

echo "Generated:"
echo "  $VIDEO"
echo "  $EDL"
