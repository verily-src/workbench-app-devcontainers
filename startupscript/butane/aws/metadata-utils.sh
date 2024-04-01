#!/bin/bash

# metadata-utils.sh defines function for aws ec2 tags.

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

