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

read -r server_url || true
registry_hostname="$(echo "${server_url}" | sed -E 's|^https?://([^/]+).*|\1|')"

readonly SECRETS_JSON="/home/core/secrets.json"
if [[ ! -f "${SECRETS_JSON}" ]]; then
  echo "Error: ${SECRETS_JSON} not found" >&2
  exit 1
fi

secret_entry="$(jq --arg registry "${registry_hostname}" \
  '.[] | select(.dockerRegistry == $registry)' \
  "${SECRETS_JSON}")"

if [[ -z "${secret_entry}" || "${secret_entry}" == "null" ]]; then
  echo "Error: No secret configured for registry ${registry_hostname}" >&2
  exit 1
fi

secret_name="$(echo "${secret_entry}" | jq -r '.name')"

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
# shellcheck source=/dev/null
source /home/core/service-utils.sh
# shellcheck source=/dev/null
source /home/core/secret-utils.sh

CLI_SERVER="$(get_metadata_value "terra-cli-server" "prod")"
WSM_URL="$(get_service_url "wsm" "${CLI_SERVER}")"

WORKSPACE_UFID="$(get_metadata_value "terra-workspace-id" "")"
if [[ -z "${WORKSPACE_UFID}" ]]; then
  echo "Error: No workspace ID found in metadata" >&2
  exit 1
fi

RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
if [[ -z "${RESOURCE_ID}" ]]; then
  echo "Error: No resource ID found in metadata" >&2
  exit 1
fi

TOKEN="$(/home/core/wb.sh auth print-access-token)"

WORKSPACE_ID="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_UFID}" \
  | jq -r '.id')"
if [[ -z "${WORKSPACE_ID}" || "${WORKSPACE_ID}" == "null" ]]; then
  echo "Error: Failed to resolve workspace UUID for '${WORKSPACE_UFID}'" >&2
  exit 1
fi

readonly KEY_FILE="/home/core/signing-key/signing.key"
if [[ ! -f "${KEY_FILE}" ]]; then
  echo "Error: Signing key not found at ${KEY_FILE}" >&2
  exit 1
fi

app_resource="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/${WORKSPACE_ID}/${RESOURCE_PATH}/${RESOURCE_ID}")"

secret_workspace_id="$(echo "${app_resource}" | jq -r --arg name "${secret_name}" '.attributes.secrets[$name].workspaceId')"
secret_resource_id="$(echo "${app_resource}" | jq -r --arg name "${secret_name}" '.attributes.secrets[$name].resourceId')"

if [[ -z "${secret_workspace_id}" || "${secret_workspace_id}" == "null" || \
      -z "${secret_resource_id}" || "${secret_resource_id}" == "null" ]]; then
  echo "Error: Secret '${secret_name}' not found in app resource's attached secrets" >&2
  exit 1
fi

validate_allowed_secret "${secret_entry}" "${secret_workspace_id}" "${secret_resource_id}"

credential="$(retrieve_secret TOKEN "${WSM_URL}" "${RESOURCE_ID}" "${KEY_FILE}" \
  "${secret_workspace_id}" "${secret_resource_id}")"

if ! echo "${credential}" | jq -e '.Username and .Secret' >/dev/null 2>&1; then
  echo "Error: Secret '${secret_name}' is not valid docker credential JSON (expected Username and Secret fields)" >&2
  exit 1
fi

echo "${credential}" | jq --arg url "${server_url}" '. + {"ServerURL": $url}'
