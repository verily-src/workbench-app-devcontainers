#!/bin/bash

# Runs as root from postStartCommand on every container start. Switches to the
# app user to refresh tokens and restart the worker, which stops with the container.
# configure-codeartifact.sh handles initial installation; this wrapper skips
# containers where that setup did not install the helper.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 user"
  exit 1
fi

readonly USER_NAME="${1}"
readonly CODEARTIFACT_REFRESH_SCRIPT="/usr/local/bin/refresh-codeartifact-login.sh"

# Installed only on AWS apps where configure-codeartifact.sh ran.
if [[ ! -x "${CODEARTIFACT_REFRESH_SCRIPT}" ]]; then
  exit 0
fi

# The worker outlives this hook, so send its output to the container log (PID
# 1's stdout), which fluent-bit ships. Only root can open it; the app user inherits it.
# shellcheck disable=SC2024 # Root opening the redirect is the point.
if ! sudo -u "${USER_NAME}" bash -l -c "'${CODEARTIFACT_REFRESH_SCRIPT}' --start" > /proc/1/fd/1 2>&1; then
  echo "WARNING: could not refresh CodeArtifact tokens; the worker will retry"
fi
