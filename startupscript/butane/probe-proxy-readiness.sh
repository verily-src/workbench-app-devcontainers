#!/bin/bash

# probe-proxy-readiness.sh checks if the proxy is up and running.
# This script requires docker to be running on the VM.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

# Wait for containers to be healthy with timeout (5 minutes)
MAX_RETRIES=150
RETRY_INTERVAL=2
retry_count=0

while [[ ${retry_count} -lt ${MAX_RETRIES} ]]; do
    APP_HEALTH="$( (docker inspect --format='{{.State.Health.Status}}' application-server 2>/dev/null || echo "none") | xargs)"

    if docker ps -q --filter "name=proxy-agent" | grep -q . \
        && docker ps -q --filter "name=application-server" | grep -q . \
        && [[ "${APP_HEALTH}" == "healthy" || "${APP_HEALTH}" == "none" ]]; then
        echo "Proxy is ready (application-server health: ${APP_HEALTH})."
        break
    fi

    retry_count=$((retry_count + 1))
    if [[ ${retry_count} -lt ${MAX_RETRIES} ]]; then
        echo "Waiting for containers to be ready (attempt ${retry_count}/${MAX_RETRIES}, app health: ${APP_HEALTH})..."
        sleep ${RETRY_INTERVAL}
    fi
done

if [[ ${retry_count} -ge ${MAX_RETRIES} ]]; then
    echo "Timeout waiting for proxy-agent or application-server to be ready"
    status="$(get_guest_attribute "startup_script/status" "")"
    if [[ "${status}" != "ERROR" ]]; then
        set_metadata "startup_script/status" "ERROR"
        set_metadata "startup_script/message" "Timeout waiting for containers to be ready. Please try restarting the VM."
    fi
    exit 1
fi

# If we reach here, the retry loop succeeded
status="$(get_guest_attribute "startup_script/status" "")"
isSuccess="false"
if [[ "${status}" != "ERROR" ]]; then
    set_metadata "startup_script/status" "COMPLETE"
    isSuccess="true"
fi

FIRST_BOOT_FILE="/home/core/first-boot"
MONITORING_UTILS_FILE="/home/core/monitoring-utils.sh"
if [[ ! -f "${FIRST_BOOT_FILE}" ]]; then
    # first boot file does not exist
    # record devcontainer end for monitoring
    source /home/core/service-utils.sh
    source "${MONITORING_UTILS_FILE}"

    # Fetch workspace ID and resourc eID
    WORKSPACE_USER_FACING_ID="$(get_metadata_value "terra-workspace-id" "")"
    SERVER="$(get_metadata_value "terra-cli-server" "prod")"
    WSM_SERVICE_URL="$(get_service_url "wsm" "${SERVER}")"
    set +o xtrace
    RESPONSE=$(curl -s -X GET "${WSM_SERVICE_URL}/api/workspaces/v1/workspaceByUserFacingId/${WORKSPACE_USER_FACING_ID}" \
                -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)")
    set -o xtrace
    WORKSPACE_ID=$(echo "${RESPONSE}" | jq -r '.id');
    RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"

    # Record devcontainer service has completed
    record_devcontainer_end "${WSM_SERVICE_URL}" "${WORKSPACE_ID}" "${RESOURCE_ID}" "${isSuccess}"
fi
touch "${FIRST_BOOT_FILE}"
