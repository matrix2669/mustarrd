#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
APP_USER="appuser"
APP_GROUP="appgroup"
LIBVA_DRIVER_NAME="${LIBVA_DRIVER_NAME:-iHD}"
export LIBVA_DRIVER_NAME

ensure_group() {
  local name="$1"
  local gid="$2"

  if getent group "${gid}" >/dev/null 2>&1; then
    return 0
  fi
  if getent group "${name}" >/dev/null 2>&1; then
    groupmod -g "${gid}" "${name}"
    return 0
  fi
  groupadd -g "${gid}" "${name}"
}

if ! getent group "${PGID}" >/dev/null 2>&1; then
  groupadd -g "${PGID}" "${APP_GROUP}"
else
  APP_GROUP="$(getent group "${PGID}" | cut -d: -f1)"
fi

if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd -m -u "${PUID}" -g "${PGID}" -s /bin/bash "${APP_USER}"
else
  usermod -u "${PUID}" -g "${PGID}" "${APP_USER}"
fi

if [[ -e /dev/dri/renderD128 ]]; then
  RENDER_GID="$(stat -c '%g' /dev/dri/renderD128)"
  ensure_group "render" "${RENDER_GID}"
  usermod -aG render "${APP_USER}"
fi

if [[ -e /dev/dri/card0 ]]; then
  VIDEO_GID="$(stat -c '%g' /dev/dri/card0)"
  ensure_group "video" "${VIDEO_GID}"
  usermod -aG video "${APP_USER}"
fi

chown -R "${PUID}:${PGID}" /app/config /app/downloads 2>/dev/null || true

if [[ -f /app/comskip.ini && ! -f /app/config/comskip.ini ]]; then
  cp /app/comskip.ini /app/config/comskip.ini
  chown "${PUID}:${PGID}" /app/config/comskip.ini 2>/dev/null || true
fi

exec gosu "${APP_USER}" "$@"
