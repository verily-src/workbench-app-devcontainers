#!/bin/bash

# vm-metadata.sh

# Retrieves a read-only vwbusr: instance attribute on the VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <key>"
    exit 1
  fi

  local tags
  tags=$(curl --retry 5 -s -f --noproxy "*" -H "Metadata:true" \
    "http://169.254.169.254/metadata/instance/compute/tagsList?api-version=2025-04-07") || {
    echo "Error: failed to fetch instance tags when retrieving ${1} metadata key" >&2
    return 1
  }

  jq -r --arg key "vwbusr:${1}" \
    'map(select(.name == $key))[0].value // ""' <<< "${tags}"
}
readonly -f get_metadata_value