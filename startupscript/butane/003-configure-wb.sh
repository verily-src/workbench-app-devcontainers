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
#
# The script is idempotent - it can be run multiple times safely and will
# only perform configuration steps that haven't already been completed.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Source configuration and utilities
source '/home/core/wb/values.sh'
source '/home/core/metadata-utils.sh'

# Create the Workbench context directory if it doesn't exist
mkdir -p "${WB_CONTEXT_DIR}"

# Get the server from metadata
SERVER="$(get_metadata_value "terra-cli-server" "")"
readonly SERVER
echo "Using server: ${SERVER}"

# Check if the Docker image needs to be built
if ! docker image inspect "${WB_IMAGE_NAME}" >/dev/null 2>&1; then
    echo "Building Workbench Docker container..."
    (
        cd "${WB_ROOT}" || exit 1
        docker build --build-arg WORKBENCH_SERVER="${SERVER}" -t "${WB_IMAGE_NAME}" .
    )
    echo "Docker image built successfully"
else
    echo "Docker image ${WB_IMAGE_NAME} already exists, skipping build"
fi

# Check if the server is already configured
current_server="$(/home/core/wb.sh server status 2>/dev/null | grep "Current server:" | sed 's/Current server: \([^ ]*\).*/\1/' || echo "")"
if [[ "${current_server}" != "${SERVER}" ]]; then
    echo "Configuring Workbench server to ${SERVER}..."
    /home/core/wb.sh server set --quiet --name "${SERVER}"
    echo "Server configured successfully"
else
    echo "Server already configured to ${SERVER}, skipping server configuration"
fi

# Check if authentication is already valid
if ! /home/core/wb.sh auth status --format json 2>/dev/null | jq -e '.loggedIn == true' >/dev/null; then
    echo "Authenticating with Workbench server using mode ${WB_LOGIN_MODE}..."
    /home/core/wb.sh auth login --mode "${WB_LOGIN_MODE}"
    echo "Authentication completed successfully"
else
    echo "Already authenticated with Workbench, skipping authentication"
fi

# Check if workspace is already configured
WORKSPACE="$(get_metadata_value "terra-workspace-id" "")"
readonly WORKSPACE
current_workspace="$(/home/core/wb.sh workspace describe --format json 2>/dev/null | jq -r '.id // empty' || echo "")"
if [[ "${current_workspace}" != "${WORKSPACE}" ]]; then
    echo "Setting Workbench workspace to ${WORKSPACE}..."
    /home/core/wb.sh workspace set --id "${WORKSPACE}"
    echo "Workspace configured successfully"
else
    echo "Workspace already set to ${WORKSPACE}, skipping workspace configuration"
fi

echo "Workbench configuration complete and up to date"
