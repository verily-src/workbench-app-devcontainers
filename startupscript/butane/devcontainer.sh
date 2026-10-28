#!/bin/bash
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/container-utils.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/app-hooks.sh"

build_app() {
    if [[ -n "${PRIMARY}" ]]; then
        echo 'Container exists; skipping build'
        return 0
    fi
    app_prepare "${CONFIG_PATH}" "${CONFIG}" "${PRIMARY}"
    if app_build_cached; then
        echo 'App starts from a local image; skipping build'
        return 0
    fi
    exec "${CLI}" build --workspace-folder "${FOLDER}"
}

start_app() {
    app_prepare "${CONFIG_PATH}" "${CONFIG}" "${PRIMARY}"
    "${CLI}" up --workspace-folder "${FOLDER}"
    app_post_up
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
WB_APP_CUSTOMIZATIONS=$(jq -c '.customizations.workbench // {}' <<< "${CONFIG}")
export WB_APP_CUSTOMIZATIONS
PRIMARY=$(get_application_container)
# Compose grants bake fs.read only for build contexts, not the CLI's generated Dockerfile.
export BUILDX_BAKE_ENTITLEMENTS_FS=0
readonly CMD FOLDER CLI CONFIG_PATH CONFIG PRIMARY WB_APP_CUSTOMIZATIONS

case "${CMD}" in
    build) build_app ;;
    up) start_app ;;
esac
