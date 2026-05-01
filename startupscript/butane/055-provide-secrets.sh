#!/bin/bash

# provide-secrets.sh
#
# Reads secrets.json (created by parse-devcontainer.sh), retrieves each secret
# value from WSM using the challenge/response signing protocol, and delivers
# them to the app container via a named pipe.
#
# Runs on the VM host after devcontainer up and before start-proxy-agent.
# Pairs with the entrypoint binary inside the container, which creates a
# named pipe at /tmp/secrets, blocks until this script writes to it, then
# exposes secrets as environment variables or file descriptors.
#
# Usage:
#   ./provide-secrets.sh <gcp/aws>
#
# Prerequisites:
#   - /home/core/secrets.json (created by parse-devcontainer.sh)
#   - /home/core/metadata-utils.sh, /home/core/service-utils.sh, /home/core/secret-utils.sh
#   - Workbench CLI configured (configure-wb.sh)
#   - Signing key registered (register-key.sh)
#   - openssl, jq

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <gcp/aws>"
  exit 1
fi

readonly CLOUD="$1"
readonly SECRETS_JSON_FILE="/home/core/secrets.json"

if [[ ! -f "${SECRETS_JSON_FILE}" ]]; then
  echo "No secrets.json found. Skipping secret provisioning."
  exit 0
fi

# --- Check for pipe-deliverable secrets early ---
PIPE_SECRETS="$(jq '[.[] | select(.pipeVar or .pathVar or .valueVar)]' "${SECRETS_JSON_FILE}")"
readonly PIPE_SECRETS

PIPE_SECRET_COUNT="$(echo "${PIPE_SECRETS}" | jq 'length')"
readonly PIPE_SECRET_COUNT

if [[ "${PIPE_SECRET_COUNT}" -eq 0 ]]; then
  echo "No pipe-deliverable secrets. Skipping."
  exit 0
fi

echo "Found ${PIPE_SECRET_COUNT} pipe-deliverable secret(s)."

# --- WSM setup ---

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
  echo "No workspace ID found in metadata. Skipping secret provisioning."
  exit 0
fi

RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
readonly RESOURCE_ID
if [[ -z "${RESOURCE_ID}" ]]; then
  echo "No resource ID found in metadata. Skipping secret provisioning."
  exit 0
fi

set +o xtrace
TOKEN="$(/home/core/wb.sh auth print-access-token)"
# shellcheck disable=SC2034
readonly TOKEN
set -o xtrace

WORKSPACE_ID="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_UFID}" \
  | jq -r '.id')"
readonly WORKSPACE_ID
if [[ -z "${WORKSPACE_ID}" || "${WORKSPACE_ID}" == "null" ]]; then
  >&2 echo "ERROR: Failed to resolve workspace UUID for '${WORKSPACE_UFID}'."
  exit 1
fi

readonly KEY_FILE="/home/core/signing-key/signing.key"
if [[ ! -f "${KEY_FILE}" ]]; then
  >&2 echo "ERROR: Signing key not found at ${KEY_FILE}. Was register-key.sh run?"
  exit 1
fi

readonly CONTAINER_NAME="application-server"
readonly PIPE_PATH="/tmp/secrets"

# --- Fetch the app resource to get attached secrets map ---
if [[ "${CLOUD}" == "gcp" ]]; then
  RESOURCE_PATH="resources/controlled/gcp/gce-instances"
elif [[ "${CLOUD}" == "aws" ]]; then
  RESOURCE_PATH="resources/controlled/aws/instances"
else
  >&2 echo "ERROR: Unsupported cloud: ${CLOUD}"
  exit 1
fi
readonly RESOURCE_PATH

APP_RESOURCE="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/${WORKSPACE_ID}/${RESOURCE_PATH}/${RESOURCE_ID}")"
readonly APP_RESOURCE

ATTACHED_SECRETS="$(echo "${APP_RESOURCE}" | jq '.attributes.secrets // {}')"
readonly ATTACHED_SECRETS

echo "Waiting for container to create named pipe..."

retries=0
until docker exec "${CONTAINER_NAME}" sh -c "[ -p ${PIPE_PATH} ]" 2>/dev/null; do
  if (( retries >= 40 )); then
    >&2 echo "ERROR: Timed out waiting for container to create ${PIPE_PATH}"
    exit 1
  fi
  sleep 3
  (( retries++ ))
done

# --- Build JSON secrets array for pipe delivery ---
SECRETS_JSON="[]"

for i in $(seq 0 $((PIPE_SECRET_COUNT - 1))); do
  SECRET_ENTRY="$(echo "${PIPE_SECRETS}" | jq ".[$i]")"
  SECRET_NAME="$(echo "${SECRET_ENTRY}" | jq -r '.name')"

  # Look up secret's workspace and resource IDs from attached secrets map
  SECRET_WORKSPACE_ID="$(echo "${ATTACHED_SECRETS}" | jq -r --arg name "${SECRET_NAME}" '.[$name].workspaceId')"
  SECRET_RESOURCE_ID="$(echo "${ATTACHED_SECRETS}" | jq -r --arg name "${SECRET_NAME}" '.[$name].resourceId')"

  if [[ -z "${SECRET_WORKSPACE_ID}" || "${SECRET_WORKSPACE_ID}" == "null" || \
        -z "${SECRET_RESOURCE_ID}" || "${SECRET_RESOURCE_ID}" == "null" ]]; then
    >&2 echo "ERROR: Secret '${SECRET_NAME}' not found in app resource's attached secrets."
    exit 1
  fi

  validate_allowed_secret "${SECRET_ENTRY}" "${SECRET_WORKSPACE_ID}" "${SECRET_RESOURCE_ID}"

  echo "Retrieving secret: ${SECRET_NAME}"

  { set +o xtrace; } 2>/dev/null
  SECRET_VALUE="$(retrieve_secret TOKEN "${WSM_URL}" "${RESOURCE_ID}" "${KEY_FILE}" \
    "${SECRET_WORKSPACE_ID}" "${SECRET_RESOURCE_ID}")"

  for SECRET_TYPE_KEY in pipeVar pathVar valueVar; do
    SECRET_TARGET="$(echo "${SECRET_ENTRY}" | jq -r ".${SECRET_TYPE_KEY} // empty")"
    if [[ -n "${SECRET_TARGET}" ]]; then
      SECRETS_JSON="$(echo "${SECRETS_JSON}" | jq \
        --arg type "${SECRET_TYPE_KEY}" \
        --arg value "${SECRET_VALUE}" \
        --arg target "${SECRET_TARGET}" \
        '. += [{"type": $type, "value": $value, "target": $target}]')"
    fi
  done
  set -o xtrace

  echo "Retrieved secret: ${SECRET_NAME}"
done

echo "Delivering ${PIPE_SECRET_COUNT} secret(s) to container..."

set +o xtrace
if ! echo "${SECRETS_JSON}" | timeout 30 docker exec -i "${CONTAINER_NAME}" sh -c "cat > ${PIPE_PATH}"; then
  >&2 echo "ERROR: Timed out writing secrets to container pipe."
  exit 1
fi

echo "Secrets delivered successfully."
