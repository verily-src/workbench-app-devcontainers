#!/bin/bash

# metadata-utils.sh defines functions for gcp instance attributes and guest attributes. This script is intended to be sourced from other scripts
# to retrieve or modify instance attributes. It is run on the VM host.

# Defines a function to retrieve an instance attributes set on the VM.
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
