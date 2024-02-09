#!/bin/bash

# vm-metadata.sh

# Defines a dummy function.

function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi
  echo ""
}
readonly -f get_metadata_value 

