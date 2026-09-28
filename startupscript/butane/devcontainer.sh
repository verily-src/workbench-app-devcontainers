#!/bin/bash
set -euo pipefail
umask 077

[[ $# == 2 && ( "$1" == build || "$1" == up ) ]] || {
    echo "Usage: $0 <build|up> <workspace-folder>" >&2; exit 1;
}
CMD=$1
FOLDER=$(cd "$2" && pwd)
CLI=${DEVCONTAINER_CLI:-/home/core/node_modules/.bin/devcontainer}
STATE_DIR="${CONTAINER_STATE_FILE:-/home/core/container-state}.d"
SNAPSHOT_IMAGE=workbench-local-snapshot:devcontainer
export WORKBENCH_SETUP_STATE_DIR="$STATE_DIR/setup"
POST_CREATE_DONE="$WORKBENCH_SETUP_STATE_DIR/post-create.done"
mkdir -p "$WORKBENCH_SETUP_STATE_DIR"
exec 9> "$STATE_DIR/lock"
flock 9
PRIMARY=$(docker ps -aq --no-trunc --filter "label=devcontainer.local_folder=$FOLDER")
CONFIG_PATH="$FOLDER/.devcontainer.json"
[[ -f "$CONFIG_PATH" ]] || CONFIG_PATH="$FOLDER/.devcontainer/devcontainer.json"
CONFIG=$(node "$(dirname "$0")/jsoncStripComments.mjs" < "$CONFIG_PATH")
AIRLOCK_ENABLED=$(jq -r '.customizations.workbench.AIRLOCK_ENABLED // false' <<< "$CONFIG")
HAS_SNAPSHOT=false
if [[ "$AIRLOCK_ENABLED" == true ]] && docker image inspect "$SNAPSHOT_IMAGE" >/dev/null 2>&1; then
    HAS_SNAPSHOT=true
fi

# A fresh container must run setup even if an earlier container completed it.
if [[ -z "$PRIMARY" && "$HAS_SNAPSHOT" == false ]]; then
    rm -f "$POST_CREATE_DONE"
fi

if [[ "$HAS_SNAPSHOT" == true ]]; then
    # Restore only the backend; leave the existing browser container untouched.
    jq '{dockerComposeFile:"docker-compose.yaml", service, runServices:[.service], workspaceFolder, customizations}' \
        <<< "$CONFIG" > "$CONFIG_PATH.tmp"
    mv "$CONFIG_PATH.tmp" "$CONFIG_PATH"
fi

if [[ "$CMD" == build && ( -n "$PRIMARY" || "$HAS_SNAPSHOT" == true ) ]]; then
    echo 'Devcontainer or snapshot already exists; skipping build'
else
    "$CLI" "$CMD" --workspace-folder "$FOLDER" --user-data-folder "$STATE_DIR/cli"
    # The CLI waits for setup and startup hooks; record success only on the host.
    if [[ "$CMD" == up ]]; then
        touch "$POST_CREATE_DONE"
        # Capture the backend once; startup must wait for this required snapshot.
        if [[ "$AIRLOCK_ENABLED" == true && "$HAS_SNAPSHOT" == false ]]; then
            PRIMARY=$(docker ps -aq --no-trunc --filter "label=devcontainer.local_folder=$FOLDER")
            docker commit "$PRIMARY" "$SNAPSHOT_IMAGE"
        fi
    fi
fi
