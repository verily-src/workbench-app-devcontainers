#!/bin/bash

# vm-metadata.sh
#
# Defines functions to retrieve an instance tag set on the VM.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and packages already installed.
#
# - aws (cli from ghcr.io/devcontainers/features/aws-cli:1)

# The get_metadata_value function is used to query for tags prefixed with "vwbusr:" attached to the
# running istance.  Tags intended for use in startup script have this prefix.  However, we have a
# temporary need to query the value of the "WorkspaceId" tag while we wait for the "no login"
# authentication mechanism for AWS to get released in all environments.  Writing get_metadata_value
# in terms of get_metadata_value_unprefixed is done for code reuse; this should be collapsed back
# down into a single get_metadata_value function once this is no longer needed.
function get_metadata_value_unprefixed() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value_unprefixed <tag>"
    exit 1
  fi

  local imds_token
  imds_token="$(wget --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)"
  local instance_id
  instance_id="$(wget --header "X-aws-ec2-metadata-token: ${imds_token}" -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  local region
  region="$(wget --header "X-aws-ec2-metadata-token: ${imds_token}" -q -O - http://169.254.169.254/latest/meta-data/placement/region)"
  aws ec2 describe-tags \
    --region "${region}" \
    --filters "Name=resource-id,Values=${instance_id}" "Name=key,Values=$1" \
    --query "Tags[0].Value" --output text 2>/dev/null
}
readonly -f get_metadata_value_unprefixed

function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <tag>"
    exit 1
  fi

  local tag_key=vwbusr:"$1"
  get_metadata_value_unprefixed "${tag_key}"
}
readonly -f get_metadata_value

# Sets tags on the EC2 instance with the given key and value. Tags set from the instance is prfixed with vwbapp:
function set_metadata() {
  local key="${1}"
  local value="${2}"
  # Per the AWS CLI documentation, value is provided within quotes,
  # with " and \ escaped with a \ prefix.
  # https://docs.aws.amazon.com/cli/latest/reference/ec2/create-tags.html
  local escaped="${value//[\"\\]/\\&}"

  echo "Creating tag vwbapp:${key} to ${value}"
  local token
  token=$(wget --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)
  local id
  id=$(wget --header "X-aws-ec2-metadata-token: ${token}" -q -O - http://169.254.169.254/latest/meta-data/instance-id)
  local region
  region="$(wget --header "X-aws-ec2-metadata-token: ${token}" -q -O - http://169.254.169.254/latest/meta-data/placement/region)"

  aws ec2 create-tags \
    --region "${region}" \
    --resources "${id}" \
    --tags Key="\"vwbapp:${key}\",Value=\"${escaped}\""
}
readonly -f set_metadata
