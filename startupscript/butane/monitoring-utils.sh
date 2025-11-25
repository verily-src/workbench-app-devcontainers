#!/bin/bash
# monitoring-utils.sh defines helper functions for notifying WSM of VM startup states.

# Log an event to WSM
function log_event() {
    if [[ $# -lt 4 ]]; then
        echo "usage: log_event <wsm_url> <workspace_id> <resource_id> <payload>" >&2
        return 1
    fi

    # Input params
    local wsm_url="$1"
    local workspace_id="$2"
    local resource_id="$3"
    local payload="$4"
    local log_url="${wsm_url}/api/workspaces/v1/${workspace_id}/resources/${resource_id}/instance-state"

    # Log VM event
    local response
    response=$(curl -s -X POST "${log_url}" \
        -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        -w "\n%{http_code}")

    local http_code
    http_code=$(echo "$response" | tail -n1)
    local response_body
    response_body=$(echo "$response" | head -n -1)

    if [[ "$http_code" != "200" ]]; then
        echo "Failed to record VM state. HTTP ${http_code}: ${response_body}" >&2
        return 1
    fi

    echo "VM state recorded successfully: ${response_body}"
}

# Record devcontainer end event
function record_devcontainer_end() {
    if [[ $# -lt 4 || ("$4" != "true" && "$4" != "false") ]]; then
        echo "usage: record_devcontainer_end <wsm_url> <workspace_id> <resource_id> <isSuccess - true/false>" >&2
        return 1
    fi

    local success="$4"
    local payload
    payload=$(cat <<EOF
{
  "event": "DEVCONTAINER_END",
  "isSuccess": ${success}
}
EOF
)
    log_event "$1" "$2" "$3" "$payload"
}
