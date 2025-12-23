#!/bin/bash

# vm-metadata.sh

echo "=== LOADING vm-metadata.sh ==="

# Retrieve instance zone of the GCE VM and extract the region.
function get_instance_region() {
  echo "  [get_instance_region] Querying GCE metadata server for zone..." >&2
  local zone_response
  zone_response=$(curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/zone" 2>&1)
  local curl_exit_code=$?

  if [[ ${curl_exit_code} -ne 0 ]]; then
    echo "  [get_instance_region] ERROR: curl failed with exit code ${curl_exit_code}" >&2
    echo "  [get_instance_region] Response: ${zone_response}" >&2
    return ${curl_exit_code}
  fi

  echo "  [get_instance_region] Zone response: ${zone_response}" >&2
  local region
  region=$(echo "${zone_response}" | awk -F'/' '{print $4}' | sed 's/-[^-]*$//')
  echo "  [get_instance_region] Extracted region: ${region}" >&2
  echo "${region}"
}
readonly -f get_instance_region

# Retrieves an instance attributes on the VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "  [get_metadata_value] ERROR: usage: get_metadata_value <tag>" >&2
    exit 1
  fi
  local metadata_path="${1}"
  echo "  [get_metadata_value] Querying metadata for: ${metadata_path}" >&2
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata/computeMetadata/v1/instance/attributes/${metadata_path}"
}
readonly -f get_metadata_value

# Sets guest attributes on the GCE VM.
function set_metadata() {
  local key="$1"
  local value="$2"
  echo "  [set_metadata] Setting guest attributes ${key} to ${value}" >&2
  local response
  response=$(curl -s -X PUT --data "${value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}" 2>&1)
  echo "  [set_metadata] Response: ${response}" >&2
}
readonly -f set_metadata

echo "=== vm-metadata.sh LOADED ==="
