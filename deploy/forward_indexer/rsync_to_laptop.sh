#!/usr/bin/env bash
set -euo pipefail

VPS_HOST="${PM_EDGE_VPS_HOST:?Set PM_EDGE_VPS_HOST, e.g. pmedge@203.0.113.10}"
REMOTE_DIR="${PM_EDGE_REMOTE_FORWARD_INDEX_DIR:-/opt/pm-edge/data/raw/forward_index/}"
LOCAL_DIR="${PM_EDGE_LOCAL_FORWARD_INDEX_DIR:-data/raw/forward_index/}"

mkdir -p "${LOCAL_DIR}"
rsync -avz --partial -e "ssh -i ~/.ssh/pm_edge_rsync" \
  "${VPS_HOST}:${REMOTE_DIR}" \
  "${LOCAL_DIR}"
