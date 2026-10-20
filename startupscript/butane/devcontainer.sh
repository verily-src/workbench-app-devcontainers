#!/bin/bash
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/container-utils.sh"

prepare_airlock() {
    umask 077
    mkdir -p "${WORKBENCH_SETUP_STATE_DIR}"

    if [[ "${HAS_SNAPSHOT}" == true ]]; then
        # Preserve the existing browser during restoration.
        jq '{dockerComposeFile:"docker-compose.yaml", service, runServices:[.service], workspaceFolder, customizations}' \
            <<< "${CONFIG}" > "${CONFIG_PATH}.tmp"
        mv "${CONFIG_PATH}.tmp" "${CONFIG_PATH}"
    elif [[ -z "${PRIMARY}" ]]; then
        # Clear stale setup state.
        rm -f "${POST_CREATE_DONE}"
    fi
}

build_app() {
    if [[ -n "${PRIMARY}" ]]; then
        echo 'Container exists; skipping build'
        return 0
    fi
    if [[ "${AIRLOCK_ENABLED}" == true ]]; then
        prepare_airlock
        if [[ "${HAS_SNAPSHOT}" == true ]]; then
            echo 'Snapshot exists; skipping build'
            return 0
        fi
    fi
    exec "${CLI}" build --workspace-folder "${FOLDER}"
}

start_app() {
    if [[ "${AIRLOCK_ENABLED}" != true ]]; then
        exec "${CLI}" up --workspace-folder "${FOLDER}"
    fi

    prepare_airlock
    "${CLI}" up --workspace-folder "${FOLDER}"
    touch "${POST_CREATE_DONE}"
    if [[ "${HAS_SNAPSHOT}" == false ]]; then
        docker commit application-server "${SNAPSHOT_IMAGE}"
    fi
}

[[ $# == 2 && ( "$1" == build || "$1" == up ) ]] || {
    echo "Usage: $0 <build|up> <workspace-folder>" >&2; exit 1;
}
CMD=$1
FOLDER=$(cd "$2" && pwd)
CLI=${DEVCONTAINER_CLI:-/home/core/node_modules/.bin/devcontainer}
CONFIG_PATH="${FOLDER}/.devcontainer.json"
[[ -f "${CONFIG_PATH}" ]] || CONFIG_PATH="${FOLDER}/.devcontainer/devcontainer.json"
CONFIG=$(node "$(dirname "$0")/jsoncStripComments.mjs" < "${CONFIG_PATH}")
AIRLOCK_ENABLED=$(jq -r '.customizations.workbench.AIRLOCK_ENABLED // false' <<< "${CONFIG}")
PRIMARY=$(get_application_container)
SNAPSHOT_IMAGE=workbench-local-snapshot:devcontainer
export WORKBENCH_SETUP_STATE_DIR="${CONTAINER_STATE_FILE:-/home/core/container-state}.d/setup"
# Compose grants bake fs.read only for build contexts, not the CLI's generated Dockerfile.
export BUILDX_BAKE_ENTITLEMENTS_FS=0
POST_CREATE_DONE="${WORKBENCH_SETUP_STATE_DIR}/post-create.done"
HAS_SNAPSHOT=false
if [[ "${AIRLOCK_ENABLED}" == true ]] && docker image inspect "${SNAPSHOT_IMAGE}" >/dev/null 2>&1; then
    HAS_SNAPSHOT=true
fi
readonly CMD FOLDER CLI CONFIG_PATH CONFIG AIRLOCK_ENABLED PRIMARY
readonly SNAPSHOT_IMAGE WORKBENCH_SETUP_STATE_DIR POST_CREATE_DONE HAS_SNAPSHOT

case "${CMD}" in
    build) build_app ;;
    up) start_app ;;
esac
