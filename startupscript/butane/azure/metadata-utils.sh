#!/bin/bash

# metadata-utils.sh defines helper functions for Azure VM tags. This script is intended to be sourced from other scripts
# to retrieve or modify VM tags. It is run on the VM host.

# Retrieves a VM tag set on the VM. If the tag is not set, it returns the default value.
function get_tag() {
  if [[ $# -lt 3 ]]; then
    echo "usage: get_tag <prefix> <tag> <default-value>"
    exit 1
  fi

  local prefix="${1}"
  local tag="${2}"
  local default="${3}"

  # Hard-coded values for prototype.
  # TODO: Replace with real implementation.
  if [[ "${prefix}" == "vwbusr" ]]; then
    case "${tag}" in
      terra-cli-server) echo "dev-stable"; return ;;
    esac
  fi

  echo "${default}"
}
readonly -f get_tag

# Azure VM uses tags instead of metadata. But to keep the interface consistent with GCP, this method retrieves tags set by the user.
# They are prefixed with vwbusr.
function get_metadata_value() {
  get_tag "vwbusr" "${1}" "${2}"
}
readonly -f get_metadata_value

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