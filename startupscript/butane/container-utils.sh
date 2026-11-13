#!/bin/bash
# Use the fixed app name; an optional frontend label selects the proxy target.

get_application_container() {
    # No match is normal before initial creation or after hardware changes.
    docker ps -aq --no-trunc --filter 'name=^/application-server$'
}

find_proxy_container() {
    local app=application-server project id
    project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "${app}") || return
    [[ -n "${project}" ]] || { echo "Error: container ${app} has no Compose project label" >&2; return 1; }
    id=$(docker ps -aq --no-trunc \
        --filter "label=com.docker.compose.project=${project}" \
        --filter 'label=com.verily.workbench.proxy-target=true') || return
    if [[ "${id}" == *$'\n'* ]]; then
        echo "Error: multiple proxy targets in Compose project ${project}" >&2
        return 1
    fi
    # Proxy traffic goes to application-server by default. For virtual-browser apps,
    # the browser's com.verily.workbench.proxy-target=true label routes it to Chromium/Selkies.
    printf '%s\n' "${id:-${app}}"
}

validate_airlock_snapshot() {
    local app="${1:-application-server}" container airlock_enabled
    local state_dir="${CONTAINER_STATE_FILE:-/home/core/container-state}.d"
    container=$(docker inspect "${app}") || return
    # The CLI preserves Workbench customizations in this label, including on restore.
    airlock_enabled=$(jq -r '
        (.[0].Config.Labels["devcontainer.metadata"] // "[]") | fromjson |
        if type == "array" then . else [.] end |
        map(.customizations.workbench // {}) | add | .AIRLOCK_ENABLED == true
    ' <<< "${container}") || return
    [[ "${airlock_enabled}" == true ]] || return 0

    if [[ ! -f "${state_dir}/setup/post-create.done" ]]; then
        echo 'Error: airlocked app setup has not completed' >&2
        return 1
    fi
    if ! docker image inspect workbench-local-snapshot:devcontainer >/dev/null 2>&1; then
        echo 'Error: airlocked app initial snapshot is unavailable' >&2
        return 1
    fi
}

containers_ready() {
    local containers
    containers=$(docker inspect "$@") || return
    jq -e '
        length > 0 and all(.[];
            .State.Running and ((.State.Health.Status // "healthy") == "healthy"))' <<< "${containers}" > /dev/null
}

# Prints "<ip>:<port>" for share-enabled VMs: the container's IPv4 address on
# app-network and the container side of its first published port. The proxy agent
# dials the container there, so X-App-Port reaches the container's ports and never
# the VM's own. Fails if the address is missing, loopback or link-local.
share_enabled_host() {
    local container="$1" inspect ip port
    inspect=$(docker inspect "${container}") || return
    ip=$(jq -r '.[0].NetworkSettings.Networks["app-network"].IPAddress // empty' <<< "${inspect}") || return
    # The same binding the default --host uses, keyed by its container port.
    port=$(jq -r '[.[0].NetworkSettings.Ports // {} | to_entries[]
        | select(any(.value[]?; .HostIp == "0.0.0.0" or .HostIp == "::"))
        | .key | split("/")[0]] | first // empty' <<< "${inspect}") || return
    if ! is_container_ipv4 "${ip}"; then
        echo "Error: ${container} has no usable IPv4 address on app-network (got '${ip}')" >&2
        return 1
    fi
    if [[ -z "${port}" ]]; then
        echo "Error: ${container} publishes no port" >&2
        return 1
    fi
    printf '%s:%s\n' "${ip}" "${port}"
}

# Returns 0 for a dotted IPv4 address that isn't unspecified, loopback or link-local.
is_container_ipv4() {
    local octet
    [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
    for octet in "${BASH_REMATCH[@]:1}"; do
        (( 10#${octet} <= 255 )) || return 1
    done
    local first=$((10#${BASH_REMATCH[1]})) second=$((10#${BASH_REMATCH[2]}))
    (( first != 0 && first != 127 && !(first == 169 && second == 254) ))
}
