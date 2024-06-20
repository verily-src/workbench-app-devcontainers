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
source /home/core/metadata-utils.sh

THRESHOLD="${1:-0.1}"
readonly CONTAINER_NAME="proxy-agent"
if [[ "$(docker container inspect -f '{{.State.Running}}' "${CONTAINER_NAME}")" == "true" ]]; then
    # Tolerates pipefail here when there's no matching log.
    # example logs: 2024/03/29 16:15:58 Forwarded request to backend
    LOG="$(docker logs "${CONTAINER_NAME}" 2>&1 | grep 'Forwarded request to backend' | tail -1 || true)"
    if [[ -n "${LOG}" ]]; then
        TIMESTAMP=$(echo "${LOG}" | awk '{print $1 " " $2}')
        UNIX_TIME=$(date -d "${TIMESTAMP}" +"%s")
        set_metadata "last-active/proxy" "${UNIX_TIME}"
    fi
fi

LOAD="$(awk '{print $3}' /proc/loadavg)" # 15-minute average load
echo "CPU load is ${LOAD}"
# Check if the LOAD has exceeded the THRESHOLD.  
# Note the use of awk for comparison of real numbers.  
if echo "${THRESHOLD}" "${LOAD}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    echo "Idling.."
else
    NOW="$(date +'%s')"
    set_metadata "last-active/cpu" "${NOW}"
fi
