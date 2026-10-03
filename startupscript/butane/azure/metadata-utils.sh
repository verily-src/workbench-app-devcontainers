#!/bin/bash

# metadata-utils.sh defines helper functions for Azure VM tags. This script is intended to be sourced from other scripts
# to retrieve or modify VM tags. It is run on the VM host.

# Azure VM uses tags for read-only metadata prefixed with `vwbusr:`.
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
function get_resource_credentials() {
  /home/core/wb.sh resource credentials --name "$(hostname)" --duration 3600 --format json
}

# Retrieves vwbapp-prefixed VM metadata from Azure Table storage.
# Tracing is disabled to prevent credential leakage in logs.
function azure_metadata_request() (
  { set +o xtrace; } 2>/dev/null
  local row_key="vwbapp:${1//\//.}" # RowKey cannot contain /, so we replace every / with .
  local default="${2}"
  local http_method="${3}"

  local resource_id
  resource_id=$(source /home/core/agent.env && echo "${BACKEND}") || return 1

  local credentials resource_uri sas_token
  credentials=$(get_resource_credentials) || return 1
  resource_uri=$(jq -er '.metadata.resourceUri' <<< "${credentials}") || return 1
  sas_token=$(jq -er '.metadata.sasToken' <<< "${credentials}") || return 1

  local response_file
  response_file=$(mktemp)
  trap 'rm -f "${response_file}"' EXIT

  local http_code
  http_code=$(
    curl --retry 5 -s -o "${response_file}" -w '%{http_code}' -H 'Accept: application/json;odata=nometadata' \
      -X "${http_method}" "${resource_uri}(PartitionKey='${resource_id}',RowKey='${row_key}')?${sas_token}"
  ) || return 1

  if [[ "${http_method}" == "GET" && "${http_code}" == "200" ]]; then
    jq -er '.Value' "${response_file}"
  elif [[ "${http_method}" == "GET" && "${http_code}" == "404" ]] &&
       jq -e '."odata.error".code | IN("EntityNotFound", "ResourceNotFound")' "${response_file}" >/dev/null; then
    echo "${default}"
  else
    echo "Error: ${http_method} guest attribute ${1} failed: HTTP ${http_code} $(<"${response_file}")" >&2
    return 1
  fi
)
readonly -f azure_metadata_request

# guest attributes are not supported on EC2 instances. But to keep the interface consistent with GCP, this method retrieves the attributes
# that are set from the instance, e.g. scripts running inside the instance. They are prefixed with vwbapp.
function get_guest_attribute() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_guest_attribute <key> <default-value>"
    exit 1
  fi
  azure_metadata_request "${1}" "${2}" GET
}
readonly -f get_guest_attribute

# Sets tags on the Azure VM with the given key and value. Tags set from the VM are is prefixed with vwbapp:
function set_metadata() {
  local key="${1}"
  local value="${2}"

  echo "Creating tag vwbapp:${key} to ${value}"
  # TODO: write tags via Azure ARM REST API using managed identity
}
readonly -f set_metadata