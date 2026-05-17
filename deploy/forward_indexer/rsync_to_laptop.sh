#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${PM_EDGE_VPS_HOST:?Set PM_EDGE_VPS_HOST, e.g. pmedge@203.0.113.10}"
REMOTE_FORWARD_INDEX_DIR="${PM_EDGE_REMOTE_FORWARD_INDEX_DIR:-/opt/pm-edge/data/raw/forward_index/}"
REMOTE_RESOLVED_DIR="${PM_EDGE_REMOTE_RESOLVED_DIR:-/opt/pm-edge/data/raw/resolved_market_outcomes/}"
LOCAL_FORWARD_INDEX_DIR="${PM_EDGE_LOCAL_FORWARD_INDEX_DIR:-data/raw/forward_index/}"
LOCAL_FORWARD_PARENT="$(dirname "${LOCAL_FORWARD_INDEX_DIR%/}")"
LOCAL_RESOLVED_DIR="${PM_EDGE_LOCAL_RESOLVED_DIR:-${LOCAL_FORWARD_PARENT}/resolved_market_outcomes/}"

check_volume_mounted() {
  local path="$1"
  local volume

  if [[ "${path}" =~ ^(/Volumes/[^/]+) ]]; then
    volume="${BASH_REMATCH[1]}"
    if ! mount | grep -q " on ${volume} "; then
      echo "[$(date -u +%FT%TZ)] External volume ${volume} is not mounted. Skipping rsync."
      echo "[$(date -u +%FT%TZ)] This is expected when the drive is ejected; reattach it to resume daily syncs."
      exit 0
    fi
  fi
}

check_volume_mounted "${LOCAL_FORWARD_INDEX_DIR}"
check_volume_mounted "${LOCAL_RESOLVED_DIR}"

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
