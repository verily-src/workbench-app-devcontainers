#!/bin/bash

CONTAINER_NAME="application-server"

exec_in_container() {
    local user="$1"
    shift
    docker exec --user "$user" "$CONTAINER_NAME" "$@"
}

run_in_container() {
    exec_in_container "${TEST_USER}" bash -l -c \
        "set -o pipefail && set -o errexit && set -o nounset && $*"
}
