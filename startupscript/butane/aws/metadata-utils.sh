#!/bin/bash

# metadata-utils.sh defines helper functions for aws ec2 tags. This script is intended to be sourced from other scripts
# to retrieve or modify instance tags. It is run on the VM host. AWS CLI is not installed on Flatcar VM by default so
# we are running the AWS CLI in a container.

# Retrieves an instance tag set on the VM. If the tag is not set, it returns the default vaule.
function get_tag() {
  if [[ $# -lt 3 ]]; then
    echo "usage: get_tag <prefix> <tag> <default-value>"
    exit 1
  fi
  local tag_key="$1":"$2"

  local token
  token=$(wget --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)
  local id
  id=$(wget --header "X-aws-ec2-metadata-token: ${token}" -q -O - http://169.254.169.254/latest/meta-data/instance-id)
  local tag_value
  tag_value="$(docker run --rm --network host \
    public.ecr.aws/aws-cli/aws-cli \
    ec2 describe-tags \
    --filters "Name=resource-id,Values=${id}" "Name=key,Values=${tag_key}" \
    --query "Tags[0].Value" --output text 2>/dev/null)"
  if [[ "${tag_value}" == "None" ]]; then
    echo "${3}"
  else
    echo "${tag_value}"
  fi
}
readonly -f get_tag 

# EC2 instance uses tags instead of metadata. But to keep the iterface consistent with GCP, this method retrieves tags set by the user.
# They are prefixed with vwbusr.
function get_metadata_value() {
  get_tag "vwbusr" "${1}" "${2}"
}
readonly -f get_metadata_value

# guest attributes are not supported on EC2 instances. But to keep the interface consistent with GCP, this method retrieves the attributes
# that are set from the instance, e.g. scripts running inside the instance. They are prefixed with vwbapp.
function get_guest_attribute() {
  get_tag "vwbapp" "${1}" "${2}"
}
readonly -f get_guest_attribute


# Sets tags on the EC2 instance with the given key and value. Tags set from the instance is prfixed with vwbapp:
function set_metadata() {
  local key="${1}"
  local value="${2}"
  
  echo "Creating tag vwbapp:${key} to ${value}"
  local token
  token=$(wget --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)
  local id
  id=$(wget --header "X-aws-ec2-metadata-token: ${token}" -q -O - http://169.254.169.254/latest/meta-data/instance-id)

  docker run --rm --detach --network host \
    public.ecr.aws/aws-cli/aws-cli \
    ec2 create-tags \
      --resources "${id}" \
      --tags Key=vwbapp:"${key}",Value="${value}"
}
readonly -f set_metadata
