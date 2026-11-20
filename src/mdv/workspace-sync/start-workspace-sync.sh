#!/bin/bash
# start-workspace-sync.sh
#
# Runs as root from postStartCommand, after remount-on-restart.sh has mounted the workspace
# buckets under the app user's ~/workspace. It:
#   1. Bind-mounts each bucket read-only under /mnt/mdv-workspace-ro, so MDV can read workspace
#      data without being able to modify it.
#   2. Runs a fast sync (link projects, no conversions) so data appears as soon as MDV is up.
#   3. Starts a background loop that converts raw files, builds the large sample project when the
#      workspace has no MDV data, and refreshes every MDV_SYNC_INTERVAL_MINUTES.
#
# Usage: start-workspace-sync.sh <app user> <app home>

set -o errexit
set -o nounset
set -o pipefail
umask 022

readonly APP_USER="${1:-pn}"
readonly APP_HOME="${2:-/home/pn}"
readonly MOUNT_ROOT="${APP_HOME}/workspace"
readonly RO_ROOT="${MDV_WORKSPACE_RO_ROOT:-/mnt/mdv-workspace-ro}"
readonly STATE_DIR="/var/lib/mdv-workspace-sync"
readonly RESOURCES_FILE="${STATE_DIR}/resources.txt"
readonly LOG_FILE="${STATE_DIR}/sync.log"
readonly PID_FILE="${STATE_DIR}/loop.pid"
readonly SYNC_DIR="/opt/mdv-workbench"
# Filesystem types treated as workspace resource mounts (gcsfuse reports fuse or fuse.gcsfuse).
readonly MOUNT_FSTYPES="${MDV_WORKSPACE_FSTYPES:-fuse fuse.gcsfuse fuse.mountpoint-s3 fuse.s3fs}"

mkdir -p "${STATE_DIR}" "${RO_ROOT}" /var/lib/mdv-samples
chown "${APP_USER}:${APP_USER}" "${STATE_DIR}" /var/lib/mdv-samples
# A failed sample build waits 6 hours before retrying; an app restart retries right away.
rm -f /var/lib/mdv-samples/.last-failure.json
# The Workspace data browser (running as the app user) appends to the same log.
touch "${LOG_FILE}" && chown "${APP_USER}:${APP_USER}" "${LOG_FILE}"
exec > >(tee -a "${LOG_FILE}") 2>&1
echo "$(date -Is) start-workspace-sync: starting"

# findmnt -r escapes spaces and other characters as \xNN; printf %b decodes them.
unescape() { printf '%b' "$1"; }

# 1. Recreate read-only bind mounts for the current set of workspace mounts.
while read -r target; do
  umount -l "${target}" || true
done < <(findmnt -rn -o TARGET | while read -r t; do
           t="$(unescape "${t}")"; [[ "${t}" == "${RO_ROOT}/"* ]] && echo "${t}"; done | sort -r)

tmp_resources="$(mktemp)"
while read -r raw_target fstype; do
  target="$(unescape "${raw_target}")"
  [[ "${target}" == "${MOUNT_ROOT}/"* ]] || continue
  [[ " ${MOUNT_FSTYPES} " == *" ${fstype} "* ]] || continue
  rel="${target#"${MOUNT_ROOT}/"}"
  dest="${RO_ROOT}/${rel}"
  mkdir -p "${dest}"
  if mount --bind "${target}" "${dest}" && mount -o remount,bind,ro "${dest}"; then
    echo "${rel}" >> "${tmp_resources}"
    echo "read-only mount: ${target} -> ${dest}"
  else
    echo "WARNING: could not mount ${target} read-only; skipping it"
    umount -l "${dest}" 2>/dev/null || true
  fi
done < <(findmnt -rn -o TARGET,FSTYPE)
install -m 0644 "${tmp_resources}" "${RESOURCES_FILE}"
rm -f "${tmp_resources}"
echo "$(wc -l < "${RESOURCES_FILE}") workspace resource(s) available to MDV"

# Workspace and resource details (names, types, descriptions) for the Workspace data browser.
# Needs the Workbench CLI logged in as the app user; without it the browser shows mount names only.
save_wb_json() {
  local dest="${STATE_DIR}/$1"; shift
  if runuser -u "${APP_USER}" -- bash -lc "timeout 60 wb $* --format=json < /dev/null" \
      > "${dest}.tmp" 2> /dev/null; then
    mv "${dest}.tmp" "${dest}"
  else
    rm -f "${dest}.tmp"
    echo "wb $* unavailable (Workbench CLI not logged in?); browser shows mount names only"
  fi
}
if command -v wb > /dev/null 2>&1; then
  save_wb_json workspace.json workspace describe
  save_wb_json resources.json resource list
fi

# 2. Fast pass: link existing projects (workspace or built-in samples) and register them.
runuser -u "${APP_USER}" -- python3 "${SYNC_DIR}/mdv_workspace_sync.py" --link-only \
  || echo "WARNING: initial sync failed; the background loop will retry"

# 3. Background loop (one per container start).
if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  echo "background sync already running (pid $(cat "${PID_FILE}"))"
  exit 0
fi
nohup setsid runuser -u "${APP_USER}" -- "${SYNC_DIR}/workspace-sync-loop.sh" \
  >> "${LOG_FILE}" 2>&1 < /dev/null &
echo $! > "${PID_FILE}"
echo "$(date -Is) start-workspace-sync: background sync started (pid $!)"
