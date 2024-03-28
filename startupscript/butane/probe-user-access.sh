#!/bin/bash

# probe-user-access.sh checks for the latest user activity on the VM based on
# cpu load and last forwarded request to the backend.
#
# usage: probe-user-access.sh <threshold>. 
# If threshold is specified, it will be used to determine cpu idlenss. When cpu 
# average usage is lower than the threshold, we determine the machine is idle.
# The default threshold is 0.1 (10 percent).

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/set-metadata.sh

readonly THRESHOLD="{$1:-0.1}"
log=$(docker logs proxy-agent 2>&1 | grep 'Forwarded request to backend' | tail -1)
if [[ -n "${log}" ]]; then
    timestamp=$(echo "${log}" | awk '{print $1 " " $2}')
    unix_time=$(date -d "${timestamp}" +"%s")
    set_metadata "last-active/proxy" "${unix_time}"
fi

load="$(awk '{print $1}' /proc/loadavg)" # 1-minute average load
echo "CPU load is ${load}"
# Check if the LOAD has exceeded the THRESHOLD.  
# Note the use of awk for comparison of real numbers.  
if echo "${THRESHOLD}" "${load}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    echo "Idling.."
else
    now="$(date +'%s')"
    set_metadata "last-active/cpu" "${now}"
fi
