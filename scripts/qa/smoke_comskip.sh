#!/usr/bin/env bash
set -euo pipefail

INPUT="${1:-}"
INI="${2:-}"

if [[ -z "$INPUT" ]]; then
  echo "Usage: $0 /path/to/video [/path/to/comskip.ini]" >&2
  exit 1
fi

if ! command -v comskip >/dev/null 2>&1; then
  echo "comskip not found in PATH." >&2
  exit 1
fi

cmd=(comskip)
if [[ -n "$INI" && -f "$INI" ]]; then
  cmd+=(--ini "$INI")
fi
cmd+=(--output "$(dirname "$INPUT")" "$INPUT")

echo "Running: ${cmd[*]}"
set +e
"${cmd[@]}"
status=$?
set -e

edl="${INPUT%.*}.edl"
if [[ -f "$edl" ]]; then
  echo "EDL generated: $edl"
else
  echo "No EDL generated (comskip exit code: $status)."
fi
