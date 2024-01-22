#!/bin/bash

# vm-metadata.sh

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

