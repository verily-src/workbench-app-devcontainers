#!/bin/bash

# Lifecycle hook, run as root on create and on every start. Prepares the
# directory where the user drops LLM API keys for the Aevom API container.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1:?Usage: setup-aevom.sh <username> <user-home-dir>}"
readonly USER_HOME_DIR="${2:?Usage: setup-aevom.sh <username> <user-home-dir>}"
readonly KEY_DIR="${USER_HOME_DIR}/.aevom"

# A named volume (aevom-keys in docker-compose.yaml) shared read-only with the
# aevom-api container. Docker creates it root-owned; hand it to the user.
mkdir -p "${KEY_DIR}"
chown "${USER_NAME}:${USER_NAME}" "${KEY_DIR}"
chmod 700 "${KEY_DIR}"

if ! find "${KEY_DIR}" -maxdepth 1 -type f -name 'API_KEY_*' -size +0 | grep -q .; then
  echo "No LLM API key yet. In a terminal run: aevom key nv   (see README)"
fi
