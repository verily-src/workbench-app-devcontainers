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

IDLE_TIMEOUT_SECONDS="$(get_metadata_value "idle-timeout-seconds" "")"
readonly IDLE_TIMEOUT_SECONDS
if [[ -z "${IDLE_TIMEOUT_SECONDS}" ]]; then
    emit "No idle timeout seconds set. Do not autostop VM."
    exit 0
fi

# Check uptime first because on VM reboot, the last active timestamp could still be really old. 
UP_TIME_SECONDS="$(awk '{print int($1)}' /proc/uptime)"
readonly UP_TIME_SECONDS

NOW="$(date +'%s')"
readonly NOW
LAST_BOOT_TIME="$((NOW - UP_TIME_SECONDS))"
readonly LAST_BOOT_TIME

# Get the last time the VM was active. Default to 0 if not set.
LAST_ACTIVE="$(get_guest_attribute "last-active/cpu" "0")"
LAST_ACTIVE_PROXY="$(get_guest_attribute "last-active/proxy" "0")"

# get the latest time between the two last active timestamps
if (( LAST_ACTIVE < LAST_ACTIVE_PROXY )); then
    LAST_ACTIVE="${LAST_ACTIVE_PROXY}"
fi
# get the latest time between the last boot time and the last active time. The last active timestamp could still be really old when the VM is rebooted and
# the last active timestamp is not updated yet.
if (( LAST_ACTIVE < LAST_BOOT_TIME )); then
    LAST_ACTIVE="${LAST_BOOT_TIME}"
fi
readonly LAST_ACTIVE
emit "Last active time: ${LAST_ACTIVE}"
set_metadata "notebooks/last_activity" "${LAST_ACTIVE}"

# Check if the VM has been idle for longer than the timeout.
if [[ $((NOW - LAST_ACTIVE)) -gt IDLE_TIMEOUT_SECONDS ]]; then
    emit "Shutting down the VM. Now time: ${NOW}. Last active time: ${LAST_ACTIVE}. Idle timeout threshold is: ${IDLE_TIMEOUT_SECONDS}"
    shutdown -h now
fi


