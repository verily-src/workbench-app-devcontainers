#!/bin/bash
# ==============================================================================
# Fluent-Bit with Cloud-Specific Logging
#
# This script runs fluent-bit in a Docker container with cloud provider-specific
# configurations for logging (GCP Stackdriver or AWS CloudWatch).
#
# Usage:
#   ./run-fluent-bit.sh <cloud>
#
# Arguments:
#   cloud - Cloud provider (gcp or aws)
#
# Environment Variables:
#   FLUENT_BIT_IMAGE    - Docker image to use (default: cr.fluentbit.io/fluent/fluent-bit:2.0-debug)
#
# Examples:
#   ./run-fluent-bit.sh gcp
#   ./run-fluent-bit.sh aws
#   FLUENT_BIT_IMAGE=fluent/fluent-bit:3.0 ./run-fluent-bit.sh gcp
#
# Prerequisites:
#   GCP: VM must have a service account with Cloud Logging permissions
#   AWS: VM must have an IAM role attached with CloudWatch Logs permissions
#   Both: Docker must be installed
# ==============================================================================

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Validate arguments
if [[ $# -ne 1 ]]; then
    echo "Error: Missing required argument"
    echo "Usage: $0 <cloud>"
    echo "  cloud: gcp or aws"
    exit 1
fi

readonly CLOUD="$1"

# Configuration with defaults
readonly FLUENT_BIT_IMAGE="${FLUENT_BIT_IMAGE:-cr.fluentbit.io/fluent/fluent-bit:2.0-debug}"

# Build Docker run command arguments
DOCKER_ARGS=(
    --rm
    --name fluent-bit
    --network host
    -v /etc/fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro
    -v /var/log/journal:/var/log/journal:ro
    -v /var/lib/docker/containers:/var/lib/docker/containers:ro
)

# Add cloud-specific configuration
case "${CLOUD}" in
    gcp)
        echo "Starting fluent-bit for GCP Stackdriver..."
        echo "  Image: ${FLUENT_BIT_IMAGE}"
        # GCP uses VM service account automatically, no additional env vars needed
        ;;

    aws)
        # Fetch instance metadata using IMDSv2
        echo "Fetching instance metadata from EC2 metadata service..."
        TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" -s)
        readonly TOKEN

        INSTANCE_ID=$(curl -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/instance-id -s)
        readonly INSTANCE_ID

        AWS_REGION=$(curl -H "X-aws-ec2-metadata-token: ${TOKEN}" http://169.254.169.254/latest/meta-data/placement/region -s)
        readonly AWS_REGION

        echo "  Instance ID: ${INSTANCE_ID}"
        echo "  Region: ${AWS_REGION}"
        echo "Starting fluent-bit for AWS CloudWatch..."
        echo "  Image: ${FLUENT_BIT_IMAGE}"

        # Add AWS-specific environment variables
        DOCKER_ARGS+=(
            --env "INSTANCE_ID=${INSTANCE_ID}"
            --env "AWS_REGION=${AWS_REGION}"
        )
        ;;

    *)
        echo "Error: Invalid cloud provider '${CLOUD}'"
        echo "Supported values: gcp, aws"
        exit 1
        ;;
esac

# Run fluent-bit in Docker container
exec /usr/bin/docker run "${DOCKER_ARGS[@]}" "${FLUENT_BIT_IMAGE}"
