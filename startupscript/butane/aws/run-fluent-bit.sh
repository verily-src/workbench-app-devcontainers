#!/bin/bash
# ==============================================================================
# Fluent-Bit CloudWatch with Instance IAM Role
#
# This script runs fluent-bit in a Docker container using the VM's existing
# IAM role credentials (via EC2 instance metadata IMDSv2).
#
# Usage:
#   ./run-fluent-bit.sh
#
# Environment Variables:
#   FLUENT_BIT_IMAGE    - Docker image to use (default: cr.fluentbit.io/fluent/fluent-bit:2.0-debug)
#
# Example:
#   ./run-fluent-bit-with-instance-role.sh
#   FLUENT_BIT_IMAGE=fluent/fluent-bit:3.0 ./run-fluent-bit-with-instance-role.sh
#
# How it works:
#   Uses --network host to allow the container to access the EC2/ECS metadata
#   service at 169.254.169.254, which provides IAM role credentials automatically.
#
# Prerequisites:
#   - VM must have an IAM role attached with CloudWatch Logs permissions
#   - Docker must be installed
# ==============================================================================

set -o errexit
set -o nounset
set -o pipefail

# Configuration with defaults
readonly FLUENT_BIT_IMAGE="${FLUENT_BIT_IMAGE:-cr.fluentbit.io/fluent/fluent-bit:2.0-debug}"
readonly FLUENT_BIT_CONFIG="${FLUENT_BIT_CONFIG:-/etc/fluent-bit.conf}"
readonly CONTAINER_NAME="${CONTAINER_NAME:-fluent-bit}"

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

# Run fluent-bit in Docker container with host networking
# Host networking allows the container to access the EC2 metadata service
echo "Starting fluent-bit container with instance IAM role..."

exec /usr/bin/docker run --rm \
    --name fluent-bit \
    --network host \
    --env "INSTANCE_ID=${INSTANCE_ID}" \
    --env "AWS_REGION=${AWS_REGION}" \
    -v /etc/fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro \
    -v /var/log/journal:/var/log/journal:ro \
    -v /var/lib/docker/containers:/var/lib/docker/containers:ro \
    "${FLUENT_BIT_IMAGE}"
