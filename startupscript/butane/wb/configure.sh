#!/bin/bash

# configure.sh - Workbench CLI Setup and Configuration
#
# This script performs initial setup and configuration for the Workbench CLI,
# preparing it for future runs via wb.sh. It handles:
# 1. Building the workbench Docker container with server configuration
# 2. Authenticating with the Workbench server
# 3. Setting up the default workspace context
#
# The script uses metadata values to configure:
# - terra-cli-server: The Workbench server endpoint
# - terra-workspace-id: The default workspace to use
#
# This is typically run once during environment setup to preconfigure
# the workbench for subsequent interactive use.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Source configuration and utilities
source '/home/core/wb/values.sh'
source '/home/core/metadata-utils.sh'

# Create the Workbench context directory if it doesn't exist
mkdir -p "${WB_CONTEXT_DIR}"

# Get the server from metadata and build container with server configuration
SERVER="$(get_metadata_value "terra-cli-server" "")"
echo "Using server: ${SERVER}"

(
    cd "${WB_ROOT}" || exit 1
    docker build --build-arg WORKBENCH_SERVER="${SERVER}" -t "${WB_IMAGE_NAME}" .
)

# Configure the Workbench CLI server setting
/home/core/wb.sh server set --name "${SERVER}"

# Authenticate with the Workbench server
echo "Logging in to Workbench CLI with mode ${WB_LOGIN_MODE}"
/home/core/wb.sh auth login --mode "${WB_LOGIN_MODE}"

# Set the default workspace context
WORKSPACE="$(get_metadata_value "terra-workspace-id" "")"
echo "Setting Workbench workspace to ${WORKSPACE}"
/home/core/wb.sh workspace set --id "${WORKSPACE}"
