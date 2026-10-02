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
