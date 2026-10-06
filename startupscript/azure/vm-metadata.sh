#!/bin/bash

# vm-metadata.sh

# Queries a single piece of VM metadata from IMDS
function _get_compute_metadata() {
  curl --retry 5 -s -f --noproxy "*" -H "Metadata:true" "http://169.254.169.254/metadata/instance/compute${1}"
}

# Retrieves a read-only vwbusr: instance attribute on the VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <key>"
    exit 1
  fi

  _get_compute_metadata "/tagsList?api-version=2025-04-07" |
    jq -r --arg key "vwbusr:${1}" 'map(select(.name == $key))[0].value // ""'
}
readonly -f get_metadata_value