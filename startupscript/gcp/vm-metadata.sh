#!/bin/bash

# vm-metadata.sh


# Retrieve the instance zone.
function get_instance_zone() {
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" | cut -d'/' -f4
}
readonly -f get_instance_zone

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
  echo "Setting guest attributes ${key} to ${value}"
  curl -s -X PUT --data "${value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f set_metadata
