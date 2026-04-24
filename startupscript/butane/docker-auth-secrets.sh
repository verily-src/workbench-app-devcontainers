#!/bin/bash

# docker-auth-secrets.sh
#
# Configures Docker to use the workbench-secret credential helper for
# registries defined as dockerRegistry secrets in secrets.json.
#
# Runs after parse-devcontainer.sh (which creates secrets.json) and before
# devcontainer build.
#
# Usage:
#   ./docker-auth-secrets.sh

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly SECRETS_JSON="/home/core/secrets.json"

if [[ ! -f "${SECRETS_JSON}" ]]; then
  echo "No secrets.json found. Skipping secret docker auth setup."
  exit 0
fi

DOCKER_REGISTRIES="$(jq -r '.[] | select(.dockerRegistry) | .dockerRegistry' "${SECRETS_JSON}")"
readonly DOCKER_REGISTRIES

if [[ -z "${DOCKER_REGISTRIES}" ]]; then
  echo "No dockerRegistry secrets found. Skipping."
  exit 0
fi

DOCKER_CONFIG_DIR="${HOME:-/root}/.docker"
readonly DOCKER_CONFIG_DIR
DOCKER_CONFIG_FILE="${DOCKER_CONFIG_DIR}/config.json"
readonly DOCKER_CONFIG_FILE

mkdir -p "${DOCKER_CONFIG_DIR}"

if [[ ! -f "${DOCKER_CONFIG_FILE}" ]]; then
  echo '{}' > "${DOCKER_CONFIG_FILE}"
fi

echo "Configuring Docker credential helpers for secret registries..."

while read -r registry_url; do
  [[ -z "${registry_url}" ]] && continue
  echo "  Configuring: ${registry_url}"
  jq --arg registry "${registry_url}" \
    '.credHelpers[$registry] = "workbench-secret"' \
    "${DOCKER_CONFIG_FILE}" > "${DOCKER_CONFIG_FILE}.tmp" && \
  mv "${DOCKER_CONFIG_FILE}.tmp" "${DOCKER_CONFIG_FILE}"
done <<< "${DOCKER_REGISTRIES}"

echo "Docker secret credential helper configuration complete."
