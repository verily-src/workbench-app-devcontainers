#!/bin/bash

# probe-proxy-readiness.sh checks if the proxy is up and running.
# This script requires docker to be running on the VM.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

if docker ps -q --filter "name=proxy-agent" | grep -q . \
    && docker ps -q --filter "name=application-server" | grep -q .; then
    echo "Proxy is ready."
    status="$(get_guest_attribute "startup_script/status" "")"
    isSuccess="false"
    if [[ "${status}" != "ERROR" ]]; then
        set_metadata "startup_script/status" "COMPLETE"
        isSuccess="true"
    fi

    FIRST_BOOT_END_FILE="/home/core/first-boot-end"
    MONITORING_UTILS_FILE="/home/core/monitoring-utils.sh"
    if [[ -f "${MONITORING_UTILS_FILE}" && ! -f "${FIRST_BOOT_END_FILE}" ]]; then
        # first boot file does not exist
        # record devcontainer end for monitoring
        source /home/core/service-utils.sh
        source "${MONITORING_UTILS_FILE}"

        # Fetch required values
        WORKSPACE_ID_CACHE_FILE="/tmp/workspace_id_cache"
        WORKSPACE_ID=$(cat "${WORKSPACE_ID_CACHE_FILE}")
        RESOURCE_ID="$(get_metadata_value "wb-resource-id" "")"
        SERVER="$(get_metadata_value "terra-cli-server" "prod")"
        WSM_SERVICE_URL="$(get_service_url "wsm" "${SERVER}")"

        record_devcontainer_end "${WSM_SERVICE_URL}" "${WORKSPACE_ID}" "${RESOURCE_ID}" "${isSuccess}"
    fi
    touch "${FIRST_BOOT_END_FILE}"
else
    echo "proxy-agent or application-server is not started"
    exit 1
fi
