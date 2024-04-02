#!/bin/bash

# metadata-utils.sh defines helper functions for aws ec2 tags. This script is intended to be sourced from other scripts
# to retrieve or modify instance tags. It is run on the VM host. AWS CLI is not installed on Flatcar VM by default so
# we are running the AWS CLI in a container.

# Defines a function to retrieve an instance tag set on the VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi
  local tag_key=vwbapp:"$1"

  INSTANCE_ID="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  docker run --rm public.ecr.aws/aws-cli/aws-cli \
   ec2 describe-tags \
    --filters "Name=resource-id,Values=${INSTANCE_ID}" "Name=key,Values=$tag_key" \
    --query "Tags[0].Value" --output text 2>/dev/null
}
readonly -f get_metadata_value

# Sets tags on the EC2 instance with the given key and value.
function set_metadata() {
  local key="$1"
  local value="$2"
  
  echo "Creating tag vwbapp:${key} to ${value}"
  local id
  id="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"

  docker run --rm public.ecr.aws/aws-cli/aws-cli \
    ec2 create-tags \
      --resources "${id}" \
      --tags Key=vwbapp:"${key}",Value="${value}"
}
readonly -f set_metadata
