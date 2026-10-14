#!/bin/bash

# metadata-utils.sh defines helper functions for Azure VM metadata. This script is intended to be sourced from other scripts
# to retrieve or modify VM metadata. It is run on the VM host.

source /home/core/agent.env

# Queries Azure VM Instance Metadata Service (IMDS) given a path and query params
function _query_imds() {
  curl --retry 5 -s -f --noproxy "*" -H "Metadata:true" \
    "http://169.254.169.254/metadata${1}" -G -d "api-version=2025-04-07"
}
readonly -f _query_imds

# Azure VM uses tags for read-only metadata prefixed with vwbusr:
function get_metadata_value() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_metadata_value <tag> <default-value>"
    exit 1
  fi

  local tags
  tags=$(_query_imds "/instance/compute/tagsList") || {
    echo "Error: failed to fetch instance tags when retrieving ${1} metadata key" >&2
    return 1
  }

  jq -r --arg key "vwbusr:${1}" --arg default "${2}" \
    'map(select(.name == $key))[0].value // $default' <<< "${tags}"
}
readonly -f get_metadata_value

# Retrieves IMDS attested document with a custom nonce.
# This token is used to uniquely identify Azure VM in Workbench API calls.
# See https://learn.microsoft.com/en-us/azure/virtual-machines/instance-metadata-service?tabs=linux#attested-data
function get_access_token() {
  # The nonce is the token expiry in epoch seconds,
  # followed by the resource UUID bytes in unpadded URL-safe base64.
  # It fits within "up to 32 random alphanumeric characters" limit from Azure spec:
  # https://github.com/Azure/azure-rest-api-specs/blob/main/specification/imds/data-plane/InstanceMetadataService/stable/2023-07-01/imds.json
  local expires_at resource_id_enc
  expires_at=$(date -d "+15 minutes" +%s)
  resource_id_enc=$(
    printf '%s' "${BACKEND//-/}" | basenc --base16 -d | basenc --base64url | tr -d '=') || return 1

  _query_imds "/attested/document?nonce=${expires_at}${resource_id_enc}" |
      jq -er 'if (.encoding // "" | ascii_downcase) == "pkcs7"
              then .signature // empty
              else error("Azure IMDS returned attested document with unknown encoding: \(.encoding)")
              end' || {
    echo "Error: failed to get attested document from Azure IMDS" >&2
    return 1
  }
}
readonly -f get_access_token

# Retrieves logs and metadata storage credentials for the Azure VM resource from WSM.
# These credentials are valid for 1 hour, and the CLI reuses cached credentials until 5 minutes before expiry.
function get_vm_resource_credentials() (
  { set -euo pipefail +o xtrace; } 2>/dev/null
  declare -F curl_with_auth >/dev/null || source /home/core/service-utils.sh

  # shellcheck disable=SC2034
  token=$(get_access_token)
  cli_server=$(get_metadata_value "terra-cli-server" "prod")
  workspace_id=$(get_metadata_value "terra-workspace-id" "")
  wsm_url=$(get_service_url "wsm" "${cli_server}")

  curl_with_auth token --retry 5 -s -f \
    "${wsm_url}/api/workspaces/v1/~${workspace_id}/resources/controlled/azure/instances/${BACKEND}/credential?durationSeconds=3600"
)
readonly -f get_vm_resource_credentials

# GETs or PUTs vwbapp-prefixed VM metadata from/to Azure Table storage.
# Tracing is disabled to prevent credential leakage in logs.
function _metadata_table_request() (
  { set -euo pipefail +o xtrace; } 2>/dev/null

  # RowKey cannot contain /, so we replace every / with .
  local row_key="vwbapp:${1//\//.}"
  local value_or_default="${2}"
  local http_method="${3}"

  local request_uri
  request_uri=$(get_vm_resource_credentials |
    jq -er --arg entity "(PartitionKey='${BACKEND}',RowKey='${row_key}')" \
      '.metadata | (.resourceUri // empty) + $entity + "?" + (.sasToken // empty)')

  local -a request_args=(-X "${http_method}" -H 'Accept: application/json;odata=nometadata')
  if [[ "${http_method}" == "PUT" ]]; then
    local payload
    payload=$(jq -n \
      --arg PartitionKey "${BACKEND}" \
      --arg RowKey "${row_key}" \
      --arg Value "${value_or_default}" '$ARGS.named')
    request_args+=(-H 'Content-Type: application/json' --data "${payload}")
  fi

  local response_file
  response_file=$(mktemp)
  trap 'rm -f "${response_file}"' EXIT

  local http_code
  http_code=$(curl --retry 5 -s -o "${response_file}" -w '%{http_code}' "${request_args[@]}" "${request_uri}")

  if [[ "${http_method}" == "PUT" && "${http_code}" == "204" ]]; then
    return
  elif [[ "${http_method}" == "GET" && "${http_code}" == "200" ]]; then
    jq -er '.Value' "${response_file}"
  elif [[ "${http_method}" == "GET" && "${http_code}" == "404" ]] &&
       jq -e '."odata.error".code | IN("EntityNotFound", "ResourceNotFound")' "${response_file}" >/dev/null; then
    echo "${value_or_default}"
  else
    echo "Error: ${http_method} guest attribute ${1} failed: HTTP ${http_code} $(<"${response_file}")" >&2
    return 1
  fi
)
readonly -f _metadata_table_request

# guest attributes are not supported on EC2 instances. But to keep the interface consistent with GCP, this method retrieves the attributes
# that are set from the instance, e.g. scripts running inside the instance. They are prefixed with vwbapp:
function get_guest_attribute() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_guest_attribute <key> <default-value>"
    exit 1
  fi
  _metadata_table_request "${1}" "${2}" GET
}
readonly -f get_guest_attribute

# Sets metadata for the Azure VM with the given key and value. Metadata keys are prefixed with vwbapp:
function set_metadata() {
  local key="${1}"
  local value="${2}"

  echo "Setting metadata vwbapp:${key} to ${value}"
  _metadata_table_request "${1}" "${2}" PUT
}
readonly -f set_metadata
