#!/usr/bin/env bats
# Test suite for container state handling in 050-parse-devcontainer.sh

setup() {
    DIR="$( cd "$( dirname "$BATS_TEST_FILENAME" )" >/dev/null 2>&1 && pwd )"
    REPO_ROOT="$(cd "${DIR}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/startupscript/butane/050-parse-devcontainer.sh"

    # The script has top-level side effects, so load only the functions under test.
    eval "$(sed -n '/^handle_container_state_changed() {/,/^}/p; /^update_container_memory_limit() {/,/^}/p' "${SCRIPT}")"

    CONTAINER_STATE_FILE="${BATS_TEST_TMPDIR}/container-state"
    DOCKER_CALLS="${BATS_TEST_TMPDIR}/docker-calls"
    # Invoked by the exported state handler in the child Bash process.
    # shellcheck disable=SC2317
    docker() {
        echo "$*" >> "${DOCKER_CALLS}"
        case "$1" in
            ps) echo backend ;;
            update) return "${UPDATE_EXIT:-0}" ;;
        esac
    }

    export CONTAINER_STATE_FILE DOCKER_CALLS
    export -f handle_container_state_changed update_container_memory_limit docker
}

run_state_change() {
    # Match startup's shell options without relying on Bats' error handling.
    run bash -euo pipefail -c 'handle_container_state_changed "$@"' -- "$@"
}

run_memory_change() {
    run bash -euo pipefail -c 'update_container_memory_limit "$@"' -- "$@"
}

@test "keeps container when state is unchanged" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m"

    [ "$status" -eq 0 ]
    [ ! -f "${DOCKER_CALLS}" ]
}

@test "removes container when GPU state changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=0" "shm-size=64m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=0" "shm-size=64m")" ]
}

@test "removes container when shared memory size changes" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=128m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=128m")" ]
}

@test "matches complete keys regardless of line order and ignores similarly named keys" {
    printf '%s\n' \
        "old-mem-limit=7000m" \
        "mem-limit-extra=9000m" \
        "shm-size=64m" \
        "gpu=1" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m"

    [ "$status" -eq 0 ]
    [ ! -f "${DOCKER_CALLS}" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m")" ]
}

@test "aborts without removing the container or overwriting state when the lookup fails" {
    printf '%s\n' "gpu=1" "shm-size=64m" > "${CONTAINER_STATE_FILE}"

    # Simulate a read failure in the child process after loading the real handler.
    # shellcheck disable=SC2317
    sed() { return 2; }
    export -f sed

    run_state_change "gpu=0" "shm-size=64m"

    [ "$status" -eq 2 ]
    [ ! -f "${DOCKER_CALLS}" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m")" ]
}

@test "missing state keys from older state files recreate only once" {
    printf '%s\n' "gpu=1" > "${CONTAINER_STATE_FILE}"

    run_state_change "gpu=1" "shm-size=64m"
    run_state_change "gpu=1" "shm-size=64m"

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = "rm -f application-server" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "shm-size=64m")" ]
}

@test "memory limit changes update the container in place" {
    local previous
    # A missing key covers state files written before the limit was tracked.
    for previous in "mem-limit=1024m" ""; do
        printf '%s\n' "gpu=1" > "${CONTAINER_STATE_FILE}"
        rm -f "${DOCKER_CALLS}"

        run_memory_change "${previous}" "mem-limit=2048m"

        [ "$status" -eq 0 ]
        [ "$(cat "${DOCKER_CALLS}")" = "$(printf '%s\n' 'ps -aq --filter name=^application-server$' \
            'update --memory 2048m --memory-swap 4096m backend')" ]
        [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "mem-limit=2048m")" ]
    done
}

@test "unchanged memory limits skip Docker" {
    printf '%s\n' "gpu=1" > "${CONTAINER_STATE_FILE}"

    run_memory_change "mem-limit=1024m" "mem-limit=1024m"

    [ "$status" -eq 0 ]
    [ ! -f "${DOCKER_CALLS}" ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "mem-limit=1024m")" ]
}

@test "an empty memory limit keeps the existing container limit" {
    printf '%s\n' "gpu=1" > "${CONTAINER_STATE_FILE}"

    run_memory_change "mem-limit=1024m" "mem-limit="

    [ "$status" -eq 0 ]
    [ "$(cat "${DOCKER_CALLS}")" = 'ps -aq --filter name=^application-server$' ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "mem-limit=")" ]
}

@test "failed memory updates are retried on the next run" {
    printf '%s\n' "gpu=1" > "${CONTAINER_STATE_FILE}"

    UPDATE_EXIT=1 run_memory_change "mem-limit=1024m" "mem-limit=2048m"

    [ "$status" -eq 0 ]
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "gpu=1" ]

    rm -f "${DOCKER_CALLS}"
    run_memory_change "" "mem-limit=2048m"

    [ "$status" -eq 0 ]
    grep -qx "update --memory 2048m --memory-swap 4096m backend" "${DOCKER_CALLS}"
    [ "$(cat "${CONTAINER_STATE_FILE}")" = "$(printf '%s\n' "gpu=1" "mem-limit=2048m")" ]
}

@test "startup applies memory limit changes in place" {
    # Match the literal variable references in the startup script.
    # shellcheck disable=SC2016
    grep -qx 'handle_container_state_changed "gpu=${gpu_exists}" "shm-size=${SHM_SIZE}"' "${SCRIPT}"
    # shellcheck disable=SC2016
    grep -qx 'update_container_memory_limit "${applied_mem_limit}" "mem-limit=${CONTAINER_MEM_LIMIT}"' "${SCRIPT}"
}
