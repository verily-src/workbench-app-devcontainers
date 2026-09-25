#!/usr/bin/env bats
# Test suite for handle_container_state_changed in 050-parse-devcontainer.sh

setup() {
    DIR="$( cd "$( dirname "$BATS_TEST_FILENAME" )" >/dev/null 2>&1 && pwd )"
    REPO_ROOT="$(cd "${DIR}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/startupscript/butane/050-parse-devcontainer.sh"

    # The script has top-level side effects, so load only the function under test.
    eval "$(sed -n '/^handle_container_state_changed() {/,/^}/p' "${SCRIPT}")"

    CONTAINER_STATE_FILE="${BATS_TEST_TMPDIR}/container-state"
    DOCKER_CALLS="${BATS_TEST_TMPDIR}/docker-calls"
    docker() { echo "$*" >> "${DOCKER_CALLS}"; }
}

@test "removes container when memory limit changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    handle_container_state_changed "gpu=1" "shm-size=64m" "mem-limit=54000m"

    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    grep -qx "mem-limit=54000m" "${CONTAINER_STATE_FILE}"
}

@test "keeps container when state is unchanged" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    handle_container_state_changed "gpu=1" "shm-size=64m" "mem-limit=27000m"

    [ ! -f "${DOCKER_CALLS}" ]
}

@test "startup tracks memory limit in container state" {
    grep -q '^handle_container_state_changed .*"mem-limit=${CONTAINER_MEM_LIMIT}"' "${SCRIPT}"
}
