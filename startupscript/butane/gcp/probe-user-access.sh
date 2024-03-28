#!/bin/bash

# probe-user-access.sh checks for the last user access forwarded by the agent.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly THRESHOLD="{$1:-0.1}"
log=$(docker logs proxy-agent 2>&1 | grep 'Forwarded request to backend' | tail -1)
if [[ -n "${log}" ]]; then
    timestamp=$(echo "${log}" | awk '{print $1 " " $2}')
    unix_time=$(date -d "${timestamp}" +"%s")
    /home/core/set-guest-attributes.sh "last-active/proxy" "${unix_time}"
fi

load="$(awk '{print $1}' /proc/loadavg)" # 1-minute average load
echo "CPU load is ${load}"
# Check if the LOAD has exceeded the THRESHOLD.  
# Note the use of awk for comparison of real numbers.  
if echo "${THRESHOLD}" "${load}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    echo "Idling.."
else
    now="$(date +'%s')"
    /home/core/set-guest-attributes.sh "last-active/cpu" "${now}"
fi
