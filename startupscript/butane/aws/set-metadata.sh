#!/bin/bash

# Creates a function set_metadata. This is expected to be sourced in other scripts
# to set tags on the EC2 instance.

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
