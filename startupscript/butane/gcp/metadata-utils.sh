#!/bin/bash

# metadata-utils.sh defines function for GCE attributes and guest attributes.
# Note that this script is intended to be sourced from scripts and is run on the VM host.

# Gets attributes on GCE VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi
  local metadata_path="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata/computeMetadata/v1/instance/attributes/${metadata_path}"
}
readonly -f get_metadata_value 

# Gets guest attributes on GCE VM.
function get_guest_attribute() {
  if [[ -z "$1" ]]; then
    echo "usage: get_guest_attribute <key>"
    exit 1
  fi
  local key="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f get_guest_attribute

# Sets guest attributes on the GCE VM.
function set_metadata() {
    local key="$1"  
    local value="$2" 
    echo "Setting metadata ${key} to ${value}"
    curl -s -X PUT --data "${value}" \
        -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f set_metadata

