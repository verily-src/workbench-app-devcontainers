#!/bin/bash

# idle-shutdown.sh shuts down the VM if it has been idle for a certain amount of time.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

# Get the idle timeout in seconds.
IDLE_TIMEOUT_SECONDS=$(get_metadata_value "idle-timeout-seconds" || echo "172800")
readonly IDLE_TIMEOUT_SECONDS

# Get the last time the VM was active.
declare LAST_ACTIVE
LAST_ACTIVE=$(get_guest_attribute "last-active/cpu" || echo "0")
LAST_ACTIVE_PROXY=$(get_guest_attribute "last-active/proxy" || echo "0")

# get the latest time between the two
if [[ "${LAST_ACTIVE}" -lt "${LAST_ACTIVE_PROXY}" ]]; then
    LAST_ACTIVE="${LAST_ACTIVE_PROXY}"
fi
echo "Last active time: ${LAST_ACTIVE}"

NOW=$(date +'%s')

# Check if the VM has been idle for longer than the timeout.
if [[ $((NOW - LAST_ACTIVE)) -gt IDLE_TIMEOUT_SECONDS ]]; then
    echo "Shutting down the VM due to inactivity."
    shutdown -h now
fi


