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

containers_ready() {
    local containers
    containers=$(docker inspect "$@") || return
    jq -e '
        length > 0 and all(.[];
            .State.Running and ((.State.Health.Status // "healthy") == "healthy"))' <<< "${containers}" > /dev/null
}
