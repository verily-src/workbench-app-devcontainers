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
    # Invoked by the exported state handler in the child Bash process.
    # shellcheck disable=SC2317
    docker() { echo "$*" >> "${DOCKER_CALLS}"; }

    export CONTAINER_STATE_FILE DOCKER_CALLS
    export -f handle_container_state_changed docker
}

run_state_change() {
    # Match startup's shell options without relying on Bats' error handling.
    run bash -euo pipefail -c 'handle_container_state_changed "$@"' -- "$@"
}

@test "removes container when memory limit changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=54000m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    grep -qx "mem-limit=54000m" "${CONTAINER_STATE_FILE}"
}

@test "keeps container when state is unchanged" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=27000m"

    [ "$status" -eq 0 ]
    [ ! -f "${DOCKER_CALLS}" ]
}

@test "removes container when GPU state changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=0" "shm-size=64m" "mem-limit=27000m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=0" "shm-size=64m" "mem-limit=27000m")" ]
}

@test "removes container when shared memory size changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=128m" "mem-limit=27000m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=128m" "mem-limit=27000m")" ]
}

@test "matches complete keys regardless of line order and ignores similarly named keys" {
    printf '%s\n' \
        "old-mem-limit=7000m" \
        "mem-limit-extra=9000m" \
        "mem-limit=27000m" \
        "shm-size=64m" \
        "gpu=1" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=27000m"

    [ "$status" -eq 0 ]
    [ ! -f "${DOCKER_CALLS}" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m")" ]
}

@test "aborts without removing the container or overwriting state when the lookup fails" {
    printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m" > "${CONTAINER_STATE_FILE}"

    # Simulate a read failure in the child process after loading the real handler.
    # shellcheck disable=SC2317
    sed() { return 2; }
    export -f sed

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=54000m"

    [ "$status" -eq 2 ]
    [ ! -f "${DOCKER_CALLS}" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=27000m")" ]
}

@test "migrates legacy state without a memory limit and recreates only once" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=14380m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=14380m")" ]

    run_state_change "gpu=1" "shm-size=64m" "mem-limit=14380m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
}

@test "migrates legacy state with an empty memory limit and recreates only once" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m" "mem-limit="

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m" "mem-limit=")" ]

    run_state_change "gpu=1" "shm-size=64m" "mem-limit="

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
}

@test "startup tracks memory limit in container state" {
    # Match the literal variable reference in the startup script.
    # shellcheck disable=SC2016
    grep -q '^handle_container_state_changed .*"mem-limit=${CONTAINER_MEM_LIMIT}"' "${SCRIPT}"
}
