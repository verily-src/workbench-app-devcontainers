#!/bin/bash

# airlock-matrix-runner.sh <username> <variant>
#
# Airlock matrix for the TEST virtual-browser apps, started by postStart. Waits
# for <prefix>/airlock-go in the workspace folder airlock-matrix-folder, runs
# the checks, and uploads <prefix>/airlock-matrix-results-<variant>.txt and
# <prefix>/airlock-matrix-done-<variant>. See README.md.
#
# PASS: egress blocked or install worked. FAIL: otherwise. SKIP: the tool is
# missing or not mirror-configured.

set -o nounset
set -o pipefail

readonly USAGE="usage: airlock-matrix-runner.sh <username> <variant>"
readonly USER_NAME="${1:?${USAGE}}"
readonly VARIANT="${2:?${USAGE}}"

# postStart runs as root; the matrix needs the app user's login environment
# (wb auth, CodeArtifact pip/npm configuration).
if [[ "$(id -u)" == "0" ]]; then
  exec sudo -u "${USER_NAME}" bash -l "$0" "$@"
fi

# The sudo login shell drops the Node feature's container PATH; use its stable
# symlink, as refresh-codeartifact-login.sh does.
readonly NVM_BIN="${NVM_DIR:-/usr/local/share/nvm}/current/bin"
if ! command -v npm >/dev/null && [[ -x "${NVM_BIN}/npm" ]]; then
  export PATH="${NVM_BIN}:${PATH}"
fi

readonly WORKBENCH_INSTALL_PATH="${WORKBENCH_INSTALL_PATH:-/usr/bin/wb}"
readonly FOLDER_NAME="airlock-matrix-folder"
readonly GO_KEY_SUFFIX="airlock-go"
readonly RESULTS_KEY_SUFFIX="airlock-matrix-results-${VARIANT}.txt"
readonly DONE_KEY_SUFFIX="airlock-matrix-done-${VARIANT}"
readonly POLL_SECONDS=20
readonly AUTH_TIMEOUT_SECONDS=$((60 * 60))
readonly GO_TIMEOUT_SECONDS=$((90 * 60))
readonly CHECK_TIMEOUT_SECONDS=300
readonly RESULTS_FILE="/tmp/airlock-matrix-results-${VARIANT}.txt"
readonly LOCK_DIR="/tmp/airlock-matrix-runner-${VARIANT}.lock"

log() {
  echo "$(date -u +%FT%TZ) airlock-matrix: $*"
}

# One runner per container lifetime; postStart fires on every container start.
if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  log "runner already started in this container; exiting"
  exit 0
fi

#############################################
# Wait for the Workbench CLI to be logged in.
#############################################
deadline=$((SECONDS + AUTH_TIMEOUT_SECONDS))
until [[ -x "${WORKBENCH_INSTALL_PATH}" ]] &&
  ! "${WORKBENCH_INSTALL_PATH}" auth status 2>&1 | grep -q "NO USER LOGGED IN"; do
  if ((SECONDS >= deadline)); then
    log "timed out waiting for wb auth; exiting"
    exit 1
  fi
  if [[ -x "${WORKBENCH_INSTALL_PATH}" ]]; then
    "${WORKBENCH_INSTALL_PATH}" auth login --mode=APP_DEFAULT_CREDENTIALS >/dev/null 2>&1 || true
  fi
  sleep "${POLL_SECONDS}"
done
log "wb auth is ready"

#########################################################
# Resolve the marker folder and the workspace AWS profile.
#########################################################
BUCKET=""
PREFIX=""
deadline=$((SECONDS + GO_TIMEOUT_SECONDS))
while [[ -z "${BUCKET}" ]]; do
  if ((SECONDS >= deadline)); then
    log "timed out waiting for the ${FOLDER_NAME} resource; exiting"
    exit 1
  fi
  folder_json="$("${WORKBENCH_INSTALL_PATH}" resource describe --name "${FOLDER_NAME}" --format=JSON 2>/dev/null)" || folder_json=""
  BUCKET="$(sed -n 's/.*"bucketName" *: *"\([^"]*\)".*/\1/p' <<<"${folder_json}" | head -1)"
  PREFIX="$(sed -n 's/.*"prefix" *: *"\([^"]*\)".*/\1/p' <<<"${folder_json}" | head -1)"
  [[ -z "${BUCKET}" ]] && sleep "${POLL_SECONDS}"
done
PREFIX="${PREFIX:-${FOLDER_NAME}}"
readonly BUCKET PREFIX
log "found marker folder s3://${BUCKET}/${PREFIX}"

export AWS_VAULT_BACKEND='file'
export AWS_VAULT_FILE_PASSPHRASE=''
eval "$("${WORKBENCH_INSTALL_PATH}" workspace configure-aws)"
export AWS_PROFILE="${FOLDER_NAME}"

s3() {
  aws s3api "$@" --bucket "${BUCKET}" >/dev/null 2>&1
}

# A previous container already finished this run.
if s3 head-object --key "${PREFIX}/${DONE_KEY_SUFFIX}"; then
  log "done marker already uploaded; exiting"
  exit 0
fi

###########################
# Wait for the "go" marker.
###########################
until s3 head-object --key "${PREFIX}/${GO_KEY_SUFFIX}"; do
  if ((SECONDS >= deadline)); then
    log "timed out waiting for the go marker; exiting"
    exit 1
  fi
  sleep "${POLL_SECONDS}"
done
log "go marker found; running the matrix"

#################
# Run the matrix.
#################
: > "${RESULTS_FILE}"
FAILURES=0

report() { # name result detail...
  local name="$1" result="$2"
  shift 2
  echo "AIRLOCK_MATRIX check=${name} result=${result} detail=$*" >> "${RESULTS_FILE}"
  [[ "${result}" == "FAIL" ]] && FAILURES=$((FAILURES + 1))
  log "check=${name} result=${result} $*"
}

run_quiet() {
  timeout "${CHECK_TIMEOUT_SECONDS}" bash -c "$1" >/dev/null 2>&1
}

expect_blocked() { # name command
  if run_quiet "$2"; then
    report "$1" FAIL "egress unexpectedly succeeded"
  else
    report "$1" PASS "blocked rc=$?"
  fi
}

expect_ok() { # name command
  if run_quiet "$2"; then
    report "$1" PASS "ok"
  else
    report "$1" FAIL "rc=$?"
  fi
}

# Direct egress must be blocked on every port.
expect_blocked curl-internet "curl -sS -m 20 https://example.com"
for port in 443 80 22 8443; do
  # The airlock drops packets, so without a short timeout each connect waits
  # out the kernel's ~2 minute SYN retries.
  expect_blocked "tcp-${port}" "timeout 10 bash -c 'echo > /dev/tcp/1.1.1.1/${port}'"
done

# Installs must work through the mirrors. An unconfigured manager is a mirror
# coverage gap, not an airlock regression, so it is SKIP.
if ! command -v pip >/dev/null; then
  report pip SKIP "pip missing"
elif ! pip config list 2>/dev/null | grep -qi codeartifact; then
  report pip SKIP "pip not mirror-configured"
else
  expect_ok pip "pip install --no-cache-dir --force-reinstall --no-deps six"
fi

if ! command -v npm >/dev/null; then
  report npm SKIP "npm missing"
elif ! npm config get registry 2>/dev/null | grep -qi codeartifact; then
  report npm SKIP "npm not mirror-configured"
else
  expect_ok npm "npm view six version"
fi

if command -v conda >/dev/null && conda config --show channels 2>/dev/null | grep -qiE "codeartifact|verily|workbench"; then
  expect_ok conda "conda search -q zlib"
else
  report conda SKIP "conda missing or not mirror-configured"
fi

if command -v Rscript >/dev/null && Rscript -e 'cat(unlist(getOption("repos")))' 2>/dev/null | grep -qiE "codeartifact|verily|workbench"; then
  expect_ok r-install "Rscript -e 'stopifnot(nrow(available.packages()) > 0)'"
else
  report r-install SKIP "R missing or not mirror-configured"
fi

if sudo -n true 2>/dev/null; then
  expect_ok apt "sudo -n apt-get update"
else
  report apt SKIP "no sudo in the app container"
fi

if command -v docker >/dev/null; then
  expect_ok docker-pull "docker pull alpine:3"
else
  report docker-pull SKIP "docker not available in the app container"
fi

echo "AIRLOCK_MATRIX_DONE failures=${FAILURES}" >> "${RESULTS_FILE}"

#####################
# Upload the results.
#####################
aws s3api put-object --bucket "${BUCKET}" --key "${PREFIX}/${RESULTS_KEY_SUFFIX}" \
  --body "${RESULTS_FILE}" >/dev/null
aws s3api put-object --bucket "${BUCKET}" --key "${PREFIX}/${DONE_KEY_SUFFIX}" >/dev/null
log "matrix complete: failures=${FAILURES}; results uploaded"
