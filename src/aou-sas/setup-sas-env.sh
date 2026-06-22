#!/bin/bash
# setup-sas-env.sh — Populate environment files for SAS Studio sessions.
#
# Runs after post-startup.sh (or remount-on-restart.sh) to create env files
# that the SAS workspace server sources on session start.
#
# - /data/.aou-env:       AoU CDR variables (from load-env)
# - /data/.workbench-env: Workbench variables (extracted from .bashrc)

set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1}"
readonly DATA_DIR="${2}"

if [ -f "/opt/sas/aou/load-env.sh" ]; then
  sudo -u "${USER_NAME}" bash -c "source '/opt/sas/aou/load-env.sh'" || true
fi

# Extract export statements from .bashrc to get workbench environment variables
grep '^export ' "${DATA_DIR}/.bashrc" > "${DATA_DIR}/.workbench-env" || true
