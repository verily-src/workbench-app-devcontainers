#!/bin/bash
# Self-update: fetch the app's branch from GitHub, stage and validate it,
# install its dependencies, activate its files, and restart the server.
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
APP_ROOT="${UPDATE_APP_ROOT:-/app}"
SHA_FILE="${APP_ROOT}/APP_SHA"
LOCK_FILE="${UPDATE_LOCK_FILE:-/tmp/cohort-studio-self-update.lock}"

log() { echo "[self-update $(date -u +%H:%M:%S)] $*"; }

# flock is provided by util-linux in the Linux devcontainer image. Keep the
# lock file in place: the kernel releases the advisory lock when fd 9 closes.
if ! command -v flock >/dev/null 2>&1; then
  log "ERROR: flock is required for safe updates"
  exit 1
fi
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  log "Another update is running; skipping."
  exit 0
fi

tmp=""
cleanup() {
  if [[ -n "${tmp}" ]]; then rm -rf "${tmp}"; fi
  flock -u 9 || true
}
trap cleanup EXIT

remote_sha="$(curl -fsSL "https://api.github.com/repos/${REPO}/commits/${BRANCH}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])')"
current_sha="$(cat "${SHA_FILE}" 2>/dev/null || echo "unknown")"

if [[ "${remote_sha}" == "${current_sha}" ]]; then
  log "Already at ${current_sha:0:9} — nothing to do."
  exit 0
fi
log "Updating ${current_sha:0:9} -> ${remote_sha:0:9}"

tmp="$(mktemp -d "${APP_ROOT}/.self-update.XXXXXX")"

curl -fsSL "https://github.com/${REPO}/archive/${remote_sha}.tar.gz" \
  -o "${tmp}/src.tgz"
tar -xzf "${tmp}/src.tgz" -C "${tmp}"
src="$(find "${tmp}" -mindepth 1 -maxdepth 1 -type d -name '*-*' | head -1)/${APP_PATH}"
if [[ ! -d "${src}/app" || ! -d "${src}/web" ]]; then
  log "ERROR: ${APP_PATH}/app not found in tarball"
  exit 1
fi

log "Staging frontend"
cd "${src}/web"
npm ci --no-audit --no-fund --silent
npm run build >/dev/null
if [[ ! -f dist/index.html ]]; then
  log "ERROR: frontend build did not produce dist/index.html"
  exit 1
fi

log "Staging backend"
mkdir -p "${tmp}/app"
cp -a "${src}/app/." "${tmp}/app/"
if [[ ! -f "${tmp}/app/main.py" || ! -f "${tmp}/app/requirements.txt" ]]; then
  log "ERROR: staged backend is missing main.py or requirements.txt"
  exit 1
fi

log "Installing staged backend dependencies"
pip install -q --no-cache-dir -r "${tmp}/app/requirements.txt"

log "Validating staged backend imports"
(cd "${tmp}/app" && PYTHONPATH="${tmp}/app${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 -c 'import main')

log "Activating staged backend"
cp -a "${tmp}/app/." "${APP_ROOT}/"

log "Activating staged frontend"
if [[ -d "${APP_ROOT}/static" ]]; then
  mv "${APP_ROOT}/static" "${tmp}/static.previous"
fi
if ! mv "${src}/web/dist" "${APP_ROOT}/static"; then
  if [[ -d "${tmp}/static.previous" ]]; then
    mv "${tmp}/static.previous" "${APP_ROOT}/static"
  fi
  log "ERROR: could not activate frontend build"
  exit 1
fi

printf '%s\n' "${remote_sha}" > "${tmp}/APP_SHA"
mv "${tmp}/APP_SHA" "${SHA_FILE}"
log "Updated to ${remote_sha:0:9}; restarting server"
# uvicorn is PID 1; the compose restart policy brings the container back
# up on the new code. '|| true' because we may be killing our own parent.
pkill -f uvicorn || true
