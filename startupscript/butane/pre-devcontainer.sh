#!/bin/bash

# pre-devcontainer.sh creates a file used by the devcontainer service for monitoring
# and to keep track of the number of service failures.

touch /tmp/devcontainer-failure-count

# Indicate first boot
source /home/core/monitoring_logs.sh
CLOUD_PLATFORM=$1
FIRST_BOOT_START_FILE="/home/core/first-boot-start"
if [[ ! -f "${FIRST_BOOT_START_FILE}" ]]; then
    # First boot file exists
    # Record startup monitoring logs
    record_devcontainer_start "${CLOUD_PLATFORM}"
fi
touch "${FIRST_BOOT_START_FILE}"