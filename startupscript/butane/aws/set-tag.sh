#!/bin/bash

# set-tag.sh sets a tag on the EC2 instance with the given key and value.
# It requires docker to be running on the VM.

set -e
if [[ $# -ne 2 ]]; then
    echo "usage: $0 <key> <value>"
    exit 1
fi
readonly AWS_CLI_EXE="docker run --rm public.ecr.aws/aws-cli/aws-cli"

id=$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)

${AWS_CLI_EXE} ec2 create-tags --resources "${id}" --tags Key=vwbapp:"$1",Value="$2"∂