#!/bin/bash

# pre-devcontainer.sh creates a file used by the devcontainer service for monitoring
# and to keep track of the number of service failures.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Keep track of the number of service failures
touch /tmp/devcontainer-failure-count

# Fetch and cache workspace_id
source /home/core/metadata-utils.sh
source /home/core/service-utils.sh
MONITORING_UTILS_FILE="/home/core/monitoring-utils.sh"
WORKSPACE_ID_CACHE_FILE="/tmp/workspace_id_cache"
FIRST_BOOT_START_FILE="/home/core/first-boot-start"
if [[ -f "${MONITORING_UTILS_FILE}" && ! -f "${FIRST_BOOT_START_FILE}" ]]; then
    # First boot file does not exist
    ## Cache workspace id to be used by probe-proxy-readiness.sh
    WORKSPACE_USER_FACING_ID="$(get_metadata_value "terra-workspace-id" "")"
    SERVER="$(get_metadata_value "terra-cli-server" "prod")"
    WSM_SERVICE_URL="$(get_service_url "wsm" "${SERVER}")"
    RESPONSE=$(curl -s -X GET "${WSM_SERVICE_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_USER_FACING_ID}" \
                -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)")
    WORKSPACE_ID=$(echo "${RESPONSE}" | jq -r '.id');
    echo "${WORKSPACE_ID}" > "${WORKSPACE_ID_CACHE_FILE}"

    ## Record devcontainer begin for monitoring
    source "${MONITORING_UTILS_FILE}"
    RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
    record_devcontainer_start "${WSM_SERVICE_URL}" "${WORKSPACE_ID}" "${RESOURCE_ID}"
fi
touch "${FIRST_BOOT_START_FILE}"
