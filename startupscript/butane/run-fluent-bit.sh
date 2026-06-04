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

# Db directory to store file offsets
mkdir -p /var/lib/fluent-bit

# Build Docker run command arguments
DOCKER_ARGS=(
    --rm
    --name fluent-bit
    --network host
    -v /etc/fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro
    -v /etc/fluent-bit/severity.lua:/fluent-bit/scripts/severity.lua:ro
    -v /var/log/journal:/var/log/journal:ro
    -v /var/lib/docker/containers:/var/lib/docker/containers:ro
    -v /var/lib/fluent-bit:/var/lib/fluent-bit
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

    azure)
        echo "Fetching instance metadata from Azure metadata service..."
        nonce=$(date -d "+5 minutes" +%s)
        TOKEN=$(curl -sH Metadata:true "http://169.254.169.254/metadata/attested/document?nonce=$nonce" -X PUT)
        readonly TOKEN # currently unused, see below

        # For now, we fetch these values from instance tags;
        # in full implementation these will be returned by WSM based on $TOKEN
        TAGS=$(curl -sH Metadata:true "http://169.254.169.254/metadata/instance/compute/tagsList?api-version=2025-04-07")
        readonly TAGS

        vm_tag() {
            echo "${TAGS}" | jq -r ".[] | select(.name == \"$1\") | .value"
        }
        STORAGE_ACCOUNT=$(vm_tag STORAGE_ACCOUNT)
        readonly STORAGE_ACCOUNT
        STORAGE_CONTAINER=$(vm_tag STORAGE_CONTAINER)
        readonly STORAGE_CONTAINER
        SAS_TOKEN_1=$(vm_tag SAS_TOKEN_1)
        readonly SAS_TOKEN_1
        SAS_TOKEN_2=$(vm_tag SAS_TOKEN_2)
        readonly SAS_TOKEN_2

        echo "  Storage account: ${STORAGE_ACCOUNT}"
        echo "  Storage container: ${STORAGE_CONTAINER}"
        echo "  SAS token: ${SAS_TOKEN_1:0:20}...${SAS_TOKEN_2:0:20}..."

        echo "Starting fluent-bit for Azure Blog log Ingestion..."
        echo "  Image: ${FLUENT_BIT_IMAGE}"

        DOCKER_ARGS+=(
            --env "STORAGE_ACCOUNT=${STORAGE_ACCOUNT}"
            --env "STORAGE_CONTAINER=${STORAGE_CONTAINER}"
            --env "SAS_TOKEN=${SAS_TOKEN_1}${SAS_TOKEN_2}"
        )
        ;;

    *)
        echo "Error: Invalid cloud provider '${CLOUD}'"
        echo "Supported values: gcp, aws, azure"
        exit 1
        ;;
esac

# Run fluent-bit in Docker container
exec /usr/bin/docker run "${DOCKER_ARGS[@]}" "${FLUENT_BIT_IMAGE}"
