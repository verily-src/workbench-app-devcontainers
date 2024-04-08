#!/bin/bash

# idle-shutdown.sh shuts down the VM if it has been idle for a certain amount of time. This script is
# run on the host VM by a systemd timer unit to check for inactivity and shut down the VM. The script
# will be run n seconds after boot up and run every m minutes. By default, it will start checking system 
# idleness 48 hours after boot and run every 5 minutes.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function emit() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

# Get the idle timeout in seconds. By default, the VM timeout after 2 days of continued idleness.
IDLE_TIMEOUT_SECONDS="${1:-172800}"

USER_TIMEOUT_OVERRIDE="$(get_metadata_value "idle-timeout-seconds")"
readonly USER_TIMEOUT_OVERRIDE
if [[ -n "${USER_TIMEOUT_OVERRIDE}" ]]; then
    emit "Overriding idle timeout with user-specified value: ${USER_TIMEOUT_OVERRIDE}"
    IDLE_TIMEOUT_SECONDS="${USER_TIMEOUT_OVERRIDE}"
fi

# Get the last time the VM was active.
LAST_ACTIVE="$(get_guest_attribute "last-active/cpu")"
LAST_ACTIVE_PROXY="$(get_guest_attribute "last-active/proxy")"

# get the latest time between the two
if [[ "${LAST_ACTIVE}" -lt "${LAST_ACTIVE_PROXY}" ]]; then
    LAST_ACTIVE="${LAST_ACTIVE_PROXY}"
fi
readonly LAST_ACTIVE
emit "Last active time: ${LAST_ACTIVE}"

NOW="$(date +'%s')"
readonly NOW

# Check if the VM has been idle for longer than the timeout.
if [[ $((NOW - LAST_ACTIVE)) -gt IDLE_TIMEOUT_SECONDS ]]; then
    emit "Shutting down the VM. Now time: ${NOW}. Last active time: ${LAST_ACTIVE}. Idle timeout threshold is: ${IDLE_TIMEOUT_SECONDS}"
    shutdown -h now
fi


