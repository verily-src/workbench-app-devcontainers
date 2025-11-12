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
    success=0
    if [[ "${status}" != "ERROR" ]]; then
        set_metadata "startup_script/status" "COMPLETE"
        success=1
    fi

    FIRST_BOOT_END_FILE="/home/core/first-boot-end"
    MONITORING_UTILS_FILE="/home/core/monitoring-utils.sh"
    if [[ -f "${MONITORING_UTILS_FILE}" && ! -f "${FIRST_BOOT_END_FILE}" ]]; then
        # first boot file does not exist
        # record startup end for monitoring
        source "${MONITORING_UTILS_FILE}"
        record_devcontainer_end "${success}"
    fi
    touch "${FIRST_BOOT_END_FILE}"
else
    echo "proxy-agent or application-server is not started"
    exit 1
fi
