#!/bin/bash

# register-key.sh
#
# Checks the app's signing algorithm and, if UNSET, generates an Ed25519
# key pair and registers the public key with the Workspace Manager.
# This runs during VM startup, before container startup.
#
# Usage:
#   ./register-key.sh <gcp/aws>
#
# Prerequisites:
#   - /home/core/metadata-utils.sh must be present
#   - /home/core/wb/values.sh must be present
#   - Workbench CLI must be configured (030-configure-wb.sh)
#   - openssl must be installed
#   - jq must be installed

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <gcp/aws>"
  exit 1
fi

readonly CLOUD="$1"

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
# shellcheck source=/dev/null
source /home/core/service-utils.sh

# Read metadata values
CLI_SERVER="$(get_metadata_value "terra-cli-server" "prod")"
readonly CLI_SERVER

WSM_URL="$(get_service_url "wsm" "${CLI_SERVER}")"
readonly WSM_URL

WORKSPACE_UFID="$(get_metadata_value "terra-workspace-id" "")"
readonly WORKSPACE_UFID
if [[ -z "${WORKSPACE_UFID}" ]]; then
  echo "No workspace ID found in metadata. Skipping key registration."
  exit 0
fi

RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
readonly RESOURCE_ID
if [[ -z "${RESOURCE_ID}" ]]; then
  echo "No resource ID found in metadata. Skipping key registration."
  exit 0
fi

# Get an access token via the Workbench CLI
set +o xtrace
TOKEN="$(/home/core/wb.sh auth print-access-token)"
# shellcheck disable=SC2034  # TOKEN is only used indirectly via curl_with_auth
readonly TOKEN
set -o xtrace

WORKSPACE_ID="$(curl_with_auth TOKEN -s -f \
  "${WSM_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_UFID}" \
  | jq -r '.id')"
readonly WORKSPACE_ID

if [[ -z "${WORKSPACE_ID}" || "${WORKSPACE_ID}" == "null" ]]; then
  >&2 echo "ERROR: Failed to resolve workspace UUID for user-facing ID '${WORKSPACE_UFID}'."
  exit 1
fi

echo "Checking signing algorithm for resource ${RESOURCE_ID}..."

if [[ "${CLOUD}" == "gcp" ]]; then
  RESOURCE_PATH="resources/controlled/gcp/gce-instances"
elif [[ "${CLOUD}" == "aws" ]]; then
  RESOURCE_PATH="resources/controlled/aws/instances"
else
  >&2 echo "ERROR: Unsupported cloud: ${CLOUD}"
  exit 1
fi
readonly RESOURCE_PATH

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "${RESPONSE_FILE}"' EXIT

RESOURCE_HTTP_CODE="$(curl_with_auth TOKEN -s \
  -o "${RESPONSE_FILE}" -w '%{http_code}' \
  "${WSM_URL}/api/workspaces/v1/${WORKSPACE_ID}/${RESOURCE_PATH}/${RESOURCE_ID}")"
readonly RESOURCE_HTTP_CODE

if [[ "${RESOURCE_HTTP_CODE}" -lt 200 || "${RESOURCE_HTTP_CODE}" -ge 300 ]]; then
  >&2 echo "ERROR: Failed to fetch resource with HTTP status ${RESOURCE_HTTP_CODE}."
  >&2 cat "${RESPONSE_FILE}"
  exit 1
fi

SIGNING_ALGORITHM="$(jq -r '.attributes.signingAlgorithm' "${RESPONSE_FILE}")"
readonly SIGNING_ALGORITHM

if [[ "${SIGNING_ALGORITHM}" != "UNSET" ]]; then
  echo "Signing algorithm is already set to '${SIGNING_ALGORITHM}'. Skipping key registration."
  exit 0
fi

echo "Signing algorithm is UNSET. Generating Ed25519 key pair..."

# Generate an Ed25519 key pair. The private key stays on the VM; the public key
# is registered with WSM.
readonly KEY_DIR="/home/core/signing-key"
mkdir -p "${KEY_DIR}"
openssl genpkey -algorithm ED25519 -out "${KEY_DIR}/signing.key" 2>/dev/null
openssl pkey -in "${KEY_DIR}/signing.key" -pubout -out "${KEY_DIR}/signing.pub" 2>/dev/null
chmod 600 "${KEY_DIR}/signing.key"

# Base64-encode the DER public key (strip PEM headers).
BASE64_PUBLIC_KEY="$(grep -v '^-----' "${KEY_DIR}/signing.pub" | tr -d '\n')"
readonly BASE64_PUBLIC_KEY

echo "Registering public key with WSM..."

# GCE Note: the registerKey endpoint MUST be used with a GCE identity token, not
# an access token, because the endpoint validates the token's compute_engine
# claims against the app resource's stored project/zone/instance name. The
# Workbench CLI returns an identity token with wb auth print-access-token so the
# same token can be used, but if this changes we will need to fetch an identity
# token from the VM metadata server instead.
#
# AWS is authorized with a pre-signed GetCallerIdentity request, which already
# contains the necessary instance information.
HTTP_CODE="$(curl_with_auth TOKEN -s -X POST \
  -o "${RESPONSE_FILE}" -w '%{http_code}' \
  -H "Content-Type: application/json" \
  "${WSM_URL}/api/workspaces/v1/${WORKSPACE_ID}/secrets/registerKey" \
  -d '{
    "appResourceId": "'"${RESOURCE_ID}"'",
    "key": "'"${BASE64_PUBLIC_KEY}"'",
    "algorithm": "ED25519"
  }')"
readonly HTTP_CODE

if [[ "${HTTP_CODE}" -eq 204 ]]; then
  echo "Key registration successful."
else
  >&2 echo "ERROR: Key registration failed with HTTP status ${HTTP_CODE}."
  >&2 cat "${RESPONSE_FILE}"
  exit 1
fi
