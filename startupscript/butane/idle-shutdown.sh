#!/bin/bash

# idle-shutdown.sh shuts down the VM if it has been idle for a certain amount of time. This script is
# run on the host VM by a systemd timer unit to check for inactivity and shut down the VM. The script
# will be run n seconds after boot up and run every m minutes. During the VM's lifetime, if the metadata
# for idle-timeout-seconds is set, the VM will be auto shutdown if it has been idled for n seconds. But
# if the metadata for idle-timeout-seconds is not set, the VM will not be auto shutdown.

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

IDLE_TIMEOUT_SECONDS="$(get_metadata_value "idle-timeout-seconds")"
readonly IDLE_TIMEOUT_SECONDS
if [[ -z "${USER_TIMEOUT_OVERRIDE}" ]]; then
    emit "No user timeout override set. Do not autostop VM."
    exit 0
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


