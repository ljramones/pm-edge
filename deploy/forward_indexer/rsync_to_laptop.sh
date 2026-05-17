#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${PM_EDGE_VPS_HOST:?Set PM_EDGE_VPS_HOST, e.g. pmedge@203.0.113.10}"
REMOTE_FORWARD_INDEX_DIR="${PM_EDGE_REMOTE_FORWARD_INDEX_DIR:-/opt/pm-edge/data/raw/forward_index/}"
REMOTE_RESOLVED_DIR="${PM_EDGE_REMOTE_RESOLVED_DIR:-/opt/pm-edge/data/raw/resolved_market_outcomes/}"
LOCAL_FORWARD_INDEX_DIR="${PM_EDGE_LOCAL_FORWARD_INDEX_DIR:-data/raw/forward_index/}"
LOCAL_FORWARD_PARENT="$(dirname "${LOCAL_FORWARD_INDEX_DIR%/}")"
LOCAL_RESOLVED_DIR="${PM_EDGE_LOCAL_RESOLVED_DIR:-${LOCAL_FORWARD_PARENT}/resolved_market_outcomes/}"

mkdir -p "${LOCAL_FORWARD_INDEX_DIR}"
mkdir -p "${LOCAL_RESOLVED_DIR}"

echo "[$(date -u +%FT%TZ)] Syncing forward_index..."
rsync -avz --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${VPS_HOST}:${REMOTE_FORWARD_INDEX_DIR}" \
  "${LOCAL_FORWARD_INDEX_DIR}"

echo "[$(date -u +%FT%TZ)] Syncing resolved_market_outcomes..."
rsync -avz --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${VPS_HOST}:${REMOTE_RESOLVED_DIR}" \
  "${LOCAL_RESOLVED_DIR}"

echo "[$(date -u +%FT%TZ)] Sync complete."
