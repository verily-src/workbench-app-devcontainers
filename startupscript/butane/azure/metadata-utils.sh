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

# guest attributes are not supported on Azure VMs. But to keep the interface consistent with GCP, this method retrieves the attributes
# that are set from the VM, e.g. scripts running inside the VM. They are prefixed with vwbapp.
function get_guest_attribute() {
  get_tag "vwbapp" "${1}" "${2}"
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