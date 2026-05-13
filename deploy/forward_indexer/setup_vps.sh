#!/usr/bin/env bash
set -euo pipefail

REMOTE="${PM_EDGE_GIT_REMOTE:-https://github.com/YOURUSERNAME/pm-edge.git}"
BRANCH="${PM_EDGE_GIT_BRANCH:-main}"
APP_DIR="${PM_EDGE_APP_DIR:-/opt/pm-edge}"
APP_USER="${PM_EDGE_APP_USER:-pmedge}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on the Ubuntu VPS." >&2
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl git rsync systemd

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="/root/.local/bin:${PATH}"
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi

mkdir -p "${APP_DIR}"
if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone --branch "${BRANCH}" "${REMOTE}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch origin "${BRANCH}"
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
fi

cd "${APP_DIR}"
uv venv .venv
uv pip install -e ".[dev]"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env from template. Edit it before production use."
fi

mkdir -p "${APP_DIR}/data/raw/forward_index"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

cp "${APP_DIR}/deploy/forward_indexer/systemd/forward-indexer.service" \
  /etc/systemd/system/forward-indexer.service
systemctl daemon-reload
systemctl enable forward-indexer.service
systemctl restart forward-indexer.service
systemctl status forward-indexer.service --no-pager
