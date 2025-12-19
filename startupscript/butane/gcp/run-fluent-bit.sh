#!/bin/bash
# ==============================================================================
# Fluent-Bit with GCP Stackdriver
#
# This script runs fluent-bit in a Docker container using the VM's service
# account credentials for Google Cloud Logging (Stackdriver).
#
# Usage:
#   ./run-fluent-bit.sh
#
# Environment Variables:
#   FLUENT_BIT_IMAGE    - Docker image to use (default: cr.fluentbit.io/fluent/fluent-bit:2.0-debug)
#
# Example:
#   ./run-fluent-bit.sh
#   FLUENT_BIT_IMAGE=fluent/fluent-bit:3.0 ./run-fluent-bit.sh
#
# Prerequisites:
#   - VM must have a service account with Cloud Logging permissions
#   - Docker must be installed
# ==============================================================================

set -o errexit
set -o nounset
set -o pipefail

# Configuration with defaults
readonly FLUENT_BIT_IMAGE="${FLUENT_BIT_IMAGE:-cr.fluentbit.io/fluent/fluent-bit:2.0-debug}"

# Run fluent-bit in Docker container
echo "Starting fluent-bit container..." >&2
echo "  Image: ${FLUENT_BIT_IMAGE}" >&2

exec /usr/bin/docker run --rm \
    --name fluent-bit \
    -v /etc/fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro \
    -v /var/log/journal:/var/log/journal:ro \
    -v /var/lib/docker/containers:/var/lib/docker/containers:ro \
    "${FLUENT_BIT_IMAGE}"
