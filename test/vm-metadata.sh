#!/bin/bash

# vm-metadata.sh

# Defines dummy functions sourced during testing.

function get_instance_region() {
  echo "us-central1"
}
readonly -f get_instance_region

function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi
  echo ""
}
readonly -f get_metadata_value

