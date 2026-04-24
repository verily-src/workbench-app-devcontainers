#!/bin/bash

# secret-utils.sh
#
# Shared functions for scripts that interact with WSM secrets.
# This script is sourced, not executed directly. It expects service-utils.sh
# to already be sourced (for curl_with_auth).

# Signs a nonce with the Ed25519 private key.
# Args:
#   $1 - nonce string
#   $2 - path to the Ed25519 private signing key
# Outputs: base64-encoded signature on stdout
function sign_nonce() {
  local nonce="$1"
  local key_file="$2"

  local nonce_file
  nonce_file="$(mktemp)"
  trap 'rm -f "${nonce_file}"' RETURN

  echo -n "${nonce}" > "${nonce_file}"
  openssl pkeyutl -sign -inkey "${key_file}" -rawin -in "${nonce_file}" \
    | base64 | tr -d '\n'
}
readonly -f sign_nonce

# Retrieves a secret value via the WSM challenge/sign/read protocol.
# Args:
#   $1 - name of the variable holding the auth token (passed to curl_with_auth)
#   $2 - WSM base URL
#   $3 - app resource ID (the challenge requestor)
#   $4 - path to the Ed25519 private signing key
#   $5 - workspace ID containing the secret
#   $6 - secret resource ID
# Outputs: decrypted secret value on stdout
function retrieve_secret() {
  local token_var="$1"
  local wsm_url="$2"
  local app_resource_id="$3"
  local key_file="$4"
  local secret_workspace_id="$5"
  local secret_resource_id="$6"

  local challenge_request
  challenge_request="$(jq -n --arg appResourceId "${app_resource_id}" \
    '{"identifier": {"appResourceId": $appResourceId}}')"

  local nonce
  nonce="$(curl_with_auth "${token_var}" -s -f -X POST \
    -H "Content-Type: application/json" \
    "${wsm_url}/api/workspaces/v1/${secret_workspace_id}/secrets/${secret_resource_id}/challenge" \
    -d "${challenge_request}" | jq -r '.nonce')"

  if [[ -z "${nonce}" || "${nonce}" == "null" ]]; then
    >&2 echo "ERROR: Failed to get challenge nonce for secret ${secret_resource_id}."
    return 1
  fi

  local signature
  signature="$(sign_nonce "${nonce}" "${key_file}")"

  local read_request
  read_request="$(jq -n \
    --arg appResourceId "${app_resource_id}" \
    --arg nonce "${nonce}" \
    --arg signature "${signature}" \
    '{
      "identifier": {"appResourceId": $appResourceId},
      "nonce": $nonce,
      "signature": $signature
    }')"

  if [[ $- == *x* ]]; then
    { set +o xtrace; } 2>/dev/null
    trap 'set -o xtrace' RETURN
  fi

  local secret_value_b64
  secret_value_b64="$(curl_with_auth "${token_var}" -s -f -X POST \
    -H "Content-Type: application/json" \
    "${wsm_url}/api/workspaces/v1/${secret_workspace_id}/secrets/${secret_resource_id}/read" \
    -d "${read_request}" | jq -r '.base64EncodedSecretValue')"

  if [[ -z "${secret_value_b64}" || "${secret_value_b64}" == "null" ]]; then
    >&2 echo "ERROR: Failed to read secret ${secret_resource_id}."
    return 1
  fi

  echo -n "${secret_value_b64}" | base64 -d
}
readonly -f retrieve_secret

# Validates that an attached secret is permitted by the entry's allowedSecrets list.
# No-op if allowedSecrets is not specified in the entry.
# Args:
#   $1 - secret entry JSON (from secrets.json)
#   $2 - workspace ID of the attached secret
#   $3 - resource ID of the attached secret
# Returns: 0 if allowed (or no restriction), 1 if not allowed
function validate_allowed_secret() {
  local secret_entry="$1"
  local workspace_id="$2"
  local resource_id="$3"

  local allowed_secrets
  allowed_secrets="$(echo "${secret_entry}" | jq '.allowedSecrets // empty')"

  if [[ -z "${allowed_secrets}" ]]; then
    return 0
  fi

  local match
  match="$(echo "${allowed_secrets}" | jq -e \
    --arg wid "${workspace_id}" \
    --arg rid "${resource_id}" \
    '[.[] | select(.workspaceId == $wid and .resourceId == $rid)] | length > 0')"

  if [[ "${match}" != "true" ]]; then
    local secret_name
    secret_name="$(echo "${secret_entry}" | jq -r '.name')"
    >&2 echo "ERROR: Attached secret '${secret_name}' (workspace=${workspace_id}, resource=${resource_id}) is not in allowedSecrets."
    return 1
  fi
}
readonly -f validate_allowed_secret
