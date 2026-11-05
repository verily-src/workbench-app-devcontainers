#!/bin/bash

# metadata-utils.sh defines functions for gcp instance attributes and guest attributes. This script is intended to be sourced from other scripts
# to retrieve or modify instance attributes. It is run on the VM host.

# Retrieves an instance attributes set on the VM. If the attribute is not set, it returns the default value.
function get_metadata_value() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_metadata_value <tag> <default-value>"
    exit 1
  fi
  local metadata_path="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata/computeMetadata/v1/instance/attributes/${metadata_path}" || echo "${2}"
}
readonly -f get_metadata_value 

# Retrieves instance guest attributes on GCE VM. If the attribute is not set, it returns the default value.
function get_guest_attribute() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_guest_attribute <key> <default-value>"
    exit 1
  fi
  local key="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}" || echo "${2}"
}
readonly -f get_guest_attribute

# Sets guest attributes on the GCE VM.
function set_metadata() {
  local key="$1"  
  local value="$2" 
  echo "Setting guest attributes ${key} to ${value}"
  curl -s -X PUT --data "${value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f set_metadata


# Returns 0 if the VM carries the share-enabled-app network tag, which WSM sets
# on VMs whose apps can be shared. If the tags can't be read, logs a warning and
# treats the VM as not share-enabled.
function is_share_enabled_vm() {
  local tags shared
  # Compare jq's output, not its exit status: jq 1.6 exits 0 on empty input.
  if ! tags="$(curl --retry 5 -s -f \
      -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/tags")" \
      || ! shared="$(jq -r 'if type == "array" then any(.[]; . == "share-enabled-app") else error end' \
        <<< "${tags}" 2>/dev/null)" \
      || [[ "${shared}" != true && "${shared}" != false ]]; then
    echo "WARNING: could not read the VM's network tags; treating it as not share-enabled." >&2
    return 1
  fi
  [[ "${shared}" == true ]]
}
readonly -f is_share_enabled_vm
