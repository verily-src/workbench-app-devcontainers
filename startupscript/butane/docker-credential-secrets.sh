#!/bin/bash

# docker-credential-secrets.sh
#
# Docker credential helper that retrieves credentials from WSM secrets.
# Called by Docker via the credential helper protocol when pulling/pushing
# to registries configured with "credHelpers": {"registry": "workbench-secret"}.
#
# Usage:
#   docker-credential-secrets.sh <resource-path> <get|store|erase|list>
#
# The resource-path argument is provided by the cloud-specific wrapper
# (e.g. "resources/controlled/gcp/gce-instances").
#
# Prerequisites:
#   - /home/core/metadata-utils.sh, /home/core/service-utils.sh, /home/core/secret-utils.sh
#   - /home/core/secrets.json (created by parse-devcontainer.sh)
#   - Signing key registered (register-key.sh)

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <resource-path> <command>" >&2
  exit 1
fi

readonly RESOURCE_PATH="$1"
readonly COMMAND="$2"

case "${COMMAND}" in
  store|erase)
    echo "Warning: ${COMMAND} is not supported by this credential helper" >&2
    cat > /dev/null
    exit 0
    ;;
  list)
    echo "{}"
    exit 0
    ;;
  get)
    ;;
  *)
    echo "Error: Invalid command '${COMMAND}'" >&2
    exit 1
    ;;
esac

# --- get: retrieve credentials for the requested registry ---

read -r SERVER_URL || true
readonly SERVER_URL
REGISTRY_HOSTNAME="$(echo "${SERVER_URL}" | sed -E 's|^https?://([^/]+).*|\1|')"
readonly REGISTRY_HOSTNAME

readonly SECRETS_JSON="/home/core/secrets.json"
if [[ ! -f "${SECRETS_JSON}" ]]; then
  echo "Error: ${SECRETS_JSON} not found" >&2
  exit 1
fi

SECRET_ENTRY="$(jq --arg registry "${REGISTRY_HOSTNAME}" \
  '.[] | select(.dockerRegistry == $registry)' \
  "${SECRETS_JSON}")"
readonly SECRET_ENTRY

if [[ -z "${SECRET_ENTRY}" || "${SECRET_ENTRY}" == "null" ]]; then
  echo "Error: No secret configured for registry ${REGISTRY_HOSTNAME}" >&2
  exit 1
fi

SECRET_NAME="$(echo "${SECRET_ENTRY}" | jq -r '.name')"
readonly SECRET_NAME

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
# shellcheck source=/dev/null
source /home/core/service-utils.sh
# shellcheck source=/dev/null
source /home/core/secret-utils.sh

CLI_SERVER="$(get_metadata_value "terra-cli-server" "prod")"
readonly CLI_SERVER

WSM_URL="$(get_service_url "wsm" "${CLI_SERVER}")"
readonly WSM_URL

WORKSPACE_UFID="$(get_metadata_value "terra-workspace-id" "")"
readonly WORKSPACE_UFID
if [[ -z "${WORKSPACE_UFID}" ]]; then
  echo "Error: No workspace ID found in metadata" >&2
  exit 1
fi

RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
readonly RESOURCE_ID
if [[ -z "${RESOURCE_ID}" ]]; then
  echo "Error: No resource ID found in metadata" >&2
  exit 1
fi

TOKEN="$(/home/core/wb.sh auth print-access-token)"
# shellcheck disable=SC2034
readonly TOKEN

WORKSPACE_ID="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_UFID}" \
  | jq -r '.id')"
readonly WORKSPACE_ID
if [[ -z "${WORKSPACE_ID}" || "${WORKSPACE_ID}" == "null" ]]; then
  echo "Error: Failed to resolve workspace UUID for '${WORKSPACE_UFID}'" >&2
  exit 1
fi

KEY_FILE="/home/core/signing-key/signing.key"
readonly KEY_FILE
if [[ ! -f "${KEY_FILE}" ]]; then
  echo "Error: Signing key not found at ${KEY_FILE}" >&2
  exit 1
fi

APP_RESOURCE="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/${WORKSPACE_ID}/${RESOURCE_PATH}/${RESOURCE_ID}")"
readonly APP_RESOURCE

SECRET_WORKSPACE_ID="$(echo "${APP_RESOURCE}" | jq -r --arg name "${SECRET_NAME}" '.attributes.secrets[$name].workspaceId')"
readonly SECRET_WORKSPACE_ID
SECRET_RESOURCE_ID="$(echo "${APP_RESOURCE}" | jq -r --arg name "${SECRET_NAME}" '.attributes.secrets[$name].resourceId')"
readonly SECRET_RESOURCE_ID

if [[ -z "${SECRET_WORKSPACE_ID}" || "${SECRET_WORKSPACE_ID}" == "null" || \
      -z "${SECRET_RESOURCE_ID}" || "${SECRET_RESOURCE_ID}" == "null" ]]; then
  echo "Error: Secret '${SECRET_NAME}' not found in app resource's attached secrets" >&2
  exit 1
fi

validate_allowed_secret "${SECRET_ENTRY}" "${SECRET_WORKSPACE_ID}" "${SECRET_RESOURCE_ID}"

CREDENTIAL="$(retrieve_secret TOKEN "${WSM_URL}" "${RESOURCE_ID}" "${KEY_FILE}" \
  "${SECRET_WORKSPACE_ID}" "${SECRET_RESOURCE_ID}")"
readonly CREDENTIAL

if ! echo "${CREDENTIAL}" | jq -e '.Username and .Secret' >/dev/null 2>&1; then
  echo "Error: Secret '${SECRET_NAME}' is not valid docker credential JSON (expected Username and Secret fields)" >&2
  exit 1
fi

echo "${CREDENTIAL}" | jq --arg url "${SERVER_URL}" '. + {"ServerURL": $url}'
