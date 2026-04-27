#!/bin/bash

CONTAINER_NAME="application-server"

run_in_container() {
    docker exec --user root "$CONTAINER_NAME" sudo -u "${TEST_USER}" bash -l -c \
        "set -o pipefail && set -o errexit && set -o nounset && $*"
}
