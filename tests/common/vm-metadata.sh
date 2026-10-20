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

function get_guest_attribute() {
  if [[ -z "$1" ]]; then
    echo "usage: get_guest_attribute <key>"
    exit 1
  fi
  echo ""
}
readonly -f get_guest_attribute

function set_metadata() {
  local key="$1"
  local value="$2"
  echo "Mock: Setting metadata ${key} to ${value}"
}
readonly -f set_metadata

