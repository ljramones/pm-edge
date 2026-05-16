#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${PM_EDGE_APP_DIR:-/opt/pm-edge}"
APP_USER="${PM_EDGE_APP_USER:-pmedge}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the Ubuntu VPS." >&2
  exit 1
fi

if [[ ! -d "${APP_DIR}" ]]; then
  echo "${APP_DIR} does not exist. Deploy the pm-edge checkout first." >&2
  exit 1
fi

mkdir -p "${APP_DIR}/data/raw/resolved_market_outcomes"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}/data/raw/resolved_market_outcomes"

cp "${APP_DIR}/deploy/resolution_watcher/systemd/resolution-watcher.service" \
  /etc/systemd/system/resolution-watcher.service
systemctl daemon-reload
systemctl enable resolution-watcher.service

echo "Installed resolution-watcher.service. Start with:"
echo "  systemctl start resolution-watcher.service"
