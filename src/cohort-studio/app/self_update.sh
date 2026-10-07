#!/bin/bash
# Self-update: fetch the app's branch from GitHub, swap backend code,
# rebuild the frontend, and restart the server.
#
# Exists to kill the slow iteration loop on Workbench VMs: app code is
# baked into the image at VM creation and a new commit normally requires
# a full VM recreate. With this script, restarting the VM (or calling
# POST /api/admin/update) redeploys the branch in about a minute.
#
# Runs inside the application container. Invoked from postStartCommand on
# every VM start and from the /api/admin/update endpoint.

set -o errexit
set -o nounset
set -o pipefail

REPO="${UPDATE_REPO:-verily-src/workbench-app-devcontainers}"
BRANCH="${UPDATE_BRANCH:-cohort-dashboard}"
APP_PATH="${UPDATE_APP_PATH:-src/cohort-studio}"
SHA_FILE="/app/APP_SHA"

log() { echo "[self-update $(date -u +%H:%M:%S)] $*"; }

remote_sha="$(curl -fsSL "https://api.github.com/repos/${REPO}/commits/${BRANCH}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
current_sha="$(cat "${SHA_FILE}" 2>/dev/null || echo "unknown")"

if [[ "${remote_sha}" == "${current_sha}" ]]; then
  log "Already at ${current_sha:0:9} — nothing to do."
  exit 0
fi
log "Updating ${current_sha:0:9} -> ${remote_sha:0:9}"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

curl -fsSL "https://github.com/${REPO}/archive/${remote_sha}.tar.gz" \
  -o "${tmp}/src.tgz"
tar -xzf "${tmp}/src.tgz" -C "${tmp}"
src="$(find "${tmp}" -maxdepth 1 -type d -name '*-*' | head -1)/${APP_PATH}"
if [[ ! -d "${src}/app" ]]; then
  log "ERROR: ${APP_PATH}/app not found in tarball"
  exit 1
fi

log "Installing backend"
cp -rf "${src}/app/." /app/
pip install -q --no-cache-dir -r /app/requirements.txt

log "Building frontend"
cd "${src}/web"
npm ci --no-audit --no-fund --silent
npm run build >/dev/null
rm -rf /app/static
cp -r dist /app/static

echo "${remote_sha}" > "${SHA_FILE}"
log "Updated to ${remote_sha:0:9}; restarting server"
# uvicorn is PID 1; the compose restart policy brings the container back
# up on the new code. '|| true' because we may be killing our own parent.
pkill -f uvicorn || true
