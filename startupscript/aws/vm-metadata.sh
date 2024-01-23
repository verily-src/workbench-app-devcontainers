#!/bin/bash

# vm-metadata.sh
#
# Defines a function to retrieve an instance tag set on the VM.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and packages already installed.
#
# - aws (cli from ghcr.io/devcontainers/features/aws-cli:1) 

function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi
  local tag_key=vwbapp:"$1"

  INSTANCE_ID="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  aws ec2 describe-tags \
    --filters "Name=resource-id,Values=${INSTANCE_ID}" "Name=key,Values=$tag_key" \
    --query "Tags[0].Value" --output text 2>/dev/null
}
readonly -f get_metadata_value 

