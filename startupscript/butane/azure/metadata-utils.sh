#!/bin/bash

# metadata-utils.sh defines helper functions for Azure VM metadata. This script is intended to be sourced from other scripts
# to retrieve or modify VM metadata. It is run on the VM host.

# Azure VM uses tags for read-only metadata prefixed with vwbusr:
function get_metadata_value() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_metadata_value <tag> <default-value>"
    exit 1
  fi

  local tags
  tags=$(curl --retry 5 -s -f --noproxy "*" -H "Metadata:true" \
    "http://169.254.169.254/metadata/instance/compute/tagsList?api-version=2025-04-07") || {
    echo "Error: failed to fetch instance tags when retrieving ${1} metadata key" >&2
    return 1
  }

  jq -r --arg key "vwbusr:${1}" --arg default "${2}" \
    'map(select(.name == $key))[0].value // $default' <<< "${tags}"
}
readonly -f get_metadata_value

# Retrieves logs and metadata storage credentials for the Azure VM resource from WSM.
# These credentials are valid for 1 hour, and the CLI reuses cached credentials until 5 minutes before expiry.
function get_vm_resource_credentials() {
  /home/core/wb.sh resource credentials --name "$(hostname)" --duration 3600 --format json
}
readonly -f get_vm_resource_credentials

# GETs or PUTs vwbapp-prefixed VM metadata from/to Azure Table storage.
# Tracing is disabled to prevent credential leakage in logs.
function _metadata_table_request() (
  { set -euo pipefail +o xtrace; } 2>/dev/null

  # RowKey cannot contain /, so we replace every / with .
  local row_key="vwbapp:${1//\//.}"
  local value_or_default="${2}"
  local http_method="${3}"

  local resource_id
  resource_id=$(source /home/core/agent.env && echo "${BACKEND}")

  local request_uri
  request_uri=$(get_vm_resource_credentials |
    jq -er --arg entity "(PartitionKey='${resource_id}',RowKey='${row_key}')" \
      '.metadata | (.resourceUri // empty) + $entity + "?" + (.sasToken // empty)')

  local -a request_args=(-X "${http_method}" -H 'Accept: application/json;odata=nometadata')
  if [[ "${http_method}" == "PUT" ]]; then
    local payload
    payload=$(jq -n \
      --arg PartitionKey "${resource_id}" \
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
