#!/bin/bash
# monitoring-utils.sh defines helper functions for notifying WSM of VM startup states.

source /home/core/service-utils.sh

WORKSPACE_ID="$(get_metadata_value "terra-workspace-id" "")"
RESOURCE_ID="$(get_metadata_value "terra-resource-id" "")"
readonly  WORKSPACE_ID RESOURCE_ID

# Get WSM endpoint URL
if ! WSM_SERVICE_URL="$(get_service_url "wsm")"; then
    exit 1
fi
LOG_URL="${WSM_SERVICE_URL}/api/workspaces/${WORKSPACE_ID}/resource/${RESOURCE_ID}/instance-state"

function record_devcontainer_end() {
    if [[ $# -lt 2 || ("$2" != "0" && "$2" != "1") ]]; then
        echo "usage: record_devcontainer_end <success/fail - 1/0>"
        exit 1
    fi
    SUCCESS="$1"
    payload=$(cat <<EOF
{
  "state": "DEVCONTAINER_END",
  "success": ${SUCCESS}
}
EOF
)
    response=$(curl -s -X POST "${LOG_URL}" \
        -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        -w "\n%{http_code}")
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)
    if [[ $http_code -ne 200 ]]; then
        echo "Failed to record VM state. HTTP ${http_code}: ${response_body}" >&2
        return 1
    fi
    echo "VM state recorded successfully: ${response_body}"
}

function record_devcontainer_start() {
    payload=$(cat <<EOF
{
  "state": "DEVCONTAINER_START",
  "success": 1
}
EOF
)
    response=$(curl -s -X POST "${LOG_URL}" \
        -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        -w "\n%{http_code}")
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)
    if [[ $http_code -ne 200 ]]; then
        echo "Failed to record VM state. HTTP ${http_code}: ${response_body}" >&2
        return 1
    fi
    echo "VM state recorded successfully: ${response_body}"
}
