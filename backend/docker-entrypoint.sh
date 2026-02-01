#!/usr/bin/env bash
set -euo pipefail

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
APP_USER="appuser"
APP_GROUP="appgroup"

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

chown -R "${PUID}:${PGID}" /app/config /app/downloads 2>/dev/null || true

if [[ -f /app/comskip.ini && ! -f /app/config/comskip.ini ]]; then
  cp /app/comskip.ini /app/config/comskip.ini
  chown "${PUID}:${PGID}" /app/config/comskip.ini 2>/dev/null || true
fi

exec gosu "${PUID}:${PGID}" "$@"
