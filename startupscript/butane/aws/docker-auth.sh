#!/bin/bash

# Docker ECR Authentication Setup
#
# This script configures Docker to use the 'workbench-ecr' credential helper
# for all ECR registries found in the current Terra Workbench environment.
# It modifies the user's Docker configuration to automatically authenticate
# with ECR repositories using Workbench credentials.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Source the ECR repository helper functions
source '/home/core/docker-repositories.sh'

# Docker config file location
# Use /root as fallback if HOME is not set (e.g., running as root non-
# interactively during systemd startup)
DOCKER_CONFIG_DIR="${HOME:-/root}/.docker"
DOCKER_CONFIG_FILE="${DOCKER_CONFIG_DIR}/config.json"

# Create Docker config directory if it doesn't exist
mkdir -p "${DOCKER_CONFIG_DIR}"

# Initialize config file if it doesn't exist
if [[ ! -f "${DOCKER_CONFIG_FILE}" ]]; then
    echo '{}' > "${DOCKER_CONFIG_FILE}"
fi

# Get all ECR registries from Workbench
echo "Configuring Docker credential helpers for ECR registries..."

# Get ECR registries and store in temp file to avoid masking exit status
temp_registries="$(mktemp)"
get_ecr_registries > "${temp_registries}"

while read -r registry_url _; do
    if [[ -n "${registry_url}" ]]; then
        echo "Configuring credential helper for registry: ${registry_url}"
        
        # Add or update the credential helper for this registry
        jq --arg registry "${registry_url}" \
           '.credHelpers[$registry] = "workbench-ecr"' \
           "${DOCKER_CONFIG_FILE}" > "${DOCKER_CONFIG_FILE}.tmp" && \
        mv "${DOCKER_CONFIG_FILE}.tmp" "${DOCKER_CONFIG_FILE}"
    fi
done < "${temp_registries}"

# Clean up temp file
rm "${temp_registries}"

echo "Docker credential helper configuration complete."
echo "Docker will now use 'workbench-ecr' helper for ECR authentication."
