#!/bin/bash

# pre-devcontainer.sh creates a file used by the devcontainer service for monitoring
# and to keep track of the number of service failures.

touch /tmp/devcontainer-failure-count

MONITORING_UTILS_FILE="/home/core/monitoring-utils.sh"
FIRST_BOOT_START_FILE="/home/core/first-boot-start"
if [[ -f "${MONITORING_UTILS_FILE}" && ! -f "${FIRST_BOOT_START_FILE}" ]]; then
    # First boot file does not exist
    # Record startup begin for monitoring
    source "${MONITORING_UTILS_FILE}"
    record_devcontainer_start "${CLOUD_PLATFORM}"
fi
touch "${FIRST_BOOT_START_FILE}"