#!/bin/bash

# Creates a function set_metadata. This is expected to be sourced in other scripts
# to set tags on the EC2 instance.

# Sets tags on the EC2 instance with the given key and value.
function set_metadata() {
  echo "Creating tag vwbapp:$1"
  readonly AWS_CLI_EXE="docker run --rm public.ecr.aws/aws-cli/aws-cli"
  local id
  id="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  docker run --rm public.ecr.aws/aws-cli/aws-cli \
    ec2 create-tags \
      --resources "${id}" \
      --tags Key=vwbapp:"$1",Value="$2"
    --resources "${id}" \
    --tags Key=vwbapp:"$1",Value="$2"
}
readonly -f set_metadata
