#!/bin/bash

# vm-metadata.sh

# Retrieve instance zone of the GCE VM and extract the region.
function get_instance_region() {
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" | \
    awk -F'/' '{print $4}' | \
    sed 's/-[^-]*$//'
}
readonly -f get_instance_region

# Retrieves an instance attributes on the VM.
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
