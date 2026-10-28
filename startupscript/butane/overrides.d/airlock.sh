#!/bin/bash

# Airlocked apps (customizations.workbench.AIRLOCK_ENABLED) keep a local
# snapshot of the application container so they can restart without internet
# access. Implements the app-hooks.sh entry points for that flow.

AIRLOCK_SNAPSHOT_IMAGE=workbench-local-snapshot:devcontainer

_airlock_enabled() {
    [[ "$(jq -r '.AIRLOCK_ENABLED // false' <<< "${WB_APP_CUSTOMIZATIONS:-null}")" == true ]]
}

_airlock_setup_dir() {
    echo "${CONTAINER_STATE_FILE:-/home/core/container-state}.d/setup"
}

_airlock_has_snapshot() {
    docker image inspect "${AIRLOCK_SNAPSHOT_IMAGE}" >/dev/null 2>&1
}

app_prepare() {
    local config_path="$1" config="$2" primary="$3"
    _airlock_enabled || return 0
    umask 077
    WORKBENCH_SETUP_STATE_DIR="$(_airlock_setup_dir)"
    export WORKBENCH_SETUP_STATE_DIR
    mkdir -p "${WORKBENCH_SETUP_STATE_DIR}"

    if _airlock_has_snapshot; then
        # Preserve the existing browser during restoration.
        jq '{dockerComposeFile:"docker-compose.yaml", service, runServices:[.service], workspaceFolder, customizations}' \
            <<< "${config}" > "${config_path}.tmp"
        mv "${config_path}.tmp" "${config_path}"
    elif [[ -z "${primary}" ]]; then
        # Clear stale setup state.
        rm -f "$(_airlock_setup_dir)/post-create.done"
    fi
}

app_build_cached() {
    _airlock_enabled && _airlock_has_snapshot
}

app_post_up() {
    _airlock_enabled || return 0
    touch "$(_airlock_setup_dir)/post-create.done"
    if ! _airlock_has_snapshot; then
        docker commit application-server "${AIRLOCK_SNAPSHOT_IMAGE}"
    fi
}

app_validate_setup() {
    local app="${1:-application-server}" container airlock_enabled
    container=$(docker inspect "${app}") || return
    # The CLI preserves Workbench customizations in this label, including on restore.
    airlock_enabled=$(jq -r '
        (.[0].Config.Labels["devcontainer.metadata"] // "[]") | fromjson |
        if type == "array" then . else [.] end |
        map(.customizations.workbench // {}) | add | .AIRLOCK_ENABLED == true
    ' <<< "${container}") || return
    [[ "${airlock_enabled}" == true ]] || return 0

    if [[ ! -f "$(_airlock_setup_dir)/post-create.done" ]]; then
        echo 'Error: airlocked app setup has not completed' >&2
        return 1
    fi
    if ! _airlock_has_snapshot; then
        echo 'Error: airlocked app initial snapshot is unavailable' >&2
        return 1
    fi
}
