#!/bin/bash
# workspace-sync-loop.sh
#
# Background loop started by start-workspace-sync.sh; runs as the MDV user. Each pass:
#   1. Syncs workspace data into MDV, including conversions of raw files.
#   2. If the workspace has no MDV data and samples are enabled, builds the large sample
#      project (once), then syncs again so it appears in MDV.
# Repeats every MDV_SYNC_INTERVAL_MINUTES (0 = run once).

set -o nounset
set -o pipefail
umask 022

readonly SYNC_DIR="/opt/mdv-workbench"
readonly INTERVAL_MINUTES="${MDV_SYNC_INTERVAL_MINUTES:-10}"
readonly SAMPLE_MODE="${MDV_SAMPLE_DATA:-auto}"
readonly STATE_FILE="${MDV_PROJECTS_DIR:-/app/mdv}/.workspace-sync-state.json"

workspace_sources() {
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("workspace_sources", 0))' \
    "${STATE_FILE}" 2>/dev/null || echo 0
}

while true; do
  echo "$(date -Is) sync pass starting"
  python3 "${SYNC_DIR}/mdv_workspace_sync.py" || echo "$(date -Is) WARNING: sync pass failed"

  if [[ "${SAMPLE_MODE}" == "always" ]] || \
     [[ "${SAMPLE_MODE}" == "auto" && "$(workspace_sources)" == "0" ]]; then
    if python3 "${SYNC_DIR}/build_samples.py"; then
      python3 "${SYNC_DIR}/mdv_workspace_sync.py" --link-only \
        || echo "$(date -Is) WARNING: sync after sample build failed"
    fi
  fi

  [[ "${INTERVAL_MINUTES}" == "0" ]] && break
  sleep "$(( INTERVAL_MINUTES * 60 ))"
done
