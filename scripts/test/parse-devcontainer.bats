#!/usr/bin/env bats
# State migration and failure cases; full parser lifecycles are tested in integration/.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    export CONTAINER_STATE_FILE="$BATS_TEST_TMPDIR/container-state"
    export DEVCONTAINER_PATH="$BATS_TEST_TMPDIR/app"
    export CALLS="$BATS_TEST_TMPDIR/calls"
    : > "$CALLS"
    LOOKUP='docker ps -aq --no-trunc --filter name=^/application-server$'
    REMOVAL="$LOOKUP
docker rm -f backend"
    sed -n '/^handle_container_state_changed() {/,/^}/p; /^update_container_memory_limit() {/,/^}/p' \
        "$REPO_ROOT/startupscript/butane/050-parse-devcontainer.sh" > "$BATS_TEST_TMPDIR/function.sh"
    # Exported into the subprocess that runs the production function.
    # shellcheck disable=SC2317
    docker() {
        echo "docker $*" >> "$CALLS"
        case "$1" in
            ps)
                [[ "${LOOKUP_EXIT:-0}" == 0 ]] || return "$LOOKUP_EXIT"
                echo backend
                ;;
            rm) return "${REMOVE_EXIT:-0}" ;;
            update) return "${UPDATE_EXIT:-0}" ;;
            *) return 1 ;;
        esac
    }
    export -f docker
}

run_function() {
    bash -euo pipefail -c 'source "$1"; source "$2"; shift 2; "$@"' \
        bash "$REPO_ROOT/startupscript/butane/container-utils.sh" "$BATS_TEST_TMPDIR/function.sh" "$@"
}

state_changed() {
    run_function handle_container_state_changed "$@"
}

memory_changed() {
    run_function update_container_memory_limit "$@"
}

@test "older state files recreate once for a missing key, including an empty value" {
    local value
    for value in '' 64m; do
        printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
        : > "$CALLS"
        state_changed 'gpu=1' "shm-size=$value"
        state_changed 'gpu=1' "shm-size=$value"
        [ "$(cat "$CONTAINER_STATE_FILE")" = "$(printf '%s\n' 'gpu=1' "shm-size=$value")" ]
        [ "$(cat "$CALLS")" = "$REMOVAL" ]
    done
}

@test "state comparison matches complete keys regardless of order" {
    printf '%s\n' 'old-mem-limit=7000m' 'mem-limit-extra=9000m' \
        'mem-limit=1024m' 'shm-size=64m' 'gpu=1' > "$CONTAINER_STATE_FILE"
    state_changed 'gpu=1' 'shm-size=64m' 'mem-limit=1024m'
    [ ! -s "$CALLS" ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = $'gpu=1\nshm-size=64m\nmem-limit=1024m' ]
}

@test "failed Docker operations preserve state until a successful retry" {
    local failure
    for failure in LOOKUP_EXIT REMOVE_EXIT; do
        printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
        export "$failure=1"
        run state_changed 'gpu=0'
        unset "$failure"
        [ "$status" -ne 0 ]
        [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=1' ]

        : > "$CALLS"
        state_changed 'gpu=0'
        [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=0' ]
        [ "$(cat "$CALLS")" = "$REMOVAL" ]
    done
}

@test "memory limit changes update the container in place" {
    local previous
    # A missing key covers state files written before the limit was tracked.
    for previous in 'mem-limit=1024m' ''; do
        printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
        : > "$CALLS"
        memory_changed "$previous" 'mem-limit=2048m'
        [ "$(cat "$CALLS")" = "$LOOKUP
docker update --memory 2048m --memory-swap 4096m backend" ]
        [ "$(cat "$CONTAINER_STATE_FILE")" = $'gpu=1\nmem-limit=2048m' ]
    done
}

@test "unchanged memory limits skip Docker" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    memory_changed 'mem-limit=1024m' 'mem-limit=1024m'
    [ ! -s "$CALLS" ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = $'gpu=1\nmem-limit=1024m' ]
}

@test "an empty memory limit keeps the existing container limit" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    memory_changed 'mem-limit=1024m' 'mem-limit='
    [ "$(cat "$CALLS")" = "$LOOKUP" ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = $'gpu=1\nmem-limit=' ]
}

@test "failed memory updates are retried on the next run" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    UPDATE_EXIT=1 memory_changed 'mem-limit=1024m' 'mem-limit=2048m'
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=1' ]

    : > "$CALLS"
    memory_changed '' 'mem-limit=2048m'
    grep -qx 'docker update --memory 2048m --memory-swap 4096m backend' "$CALLS"
    [ "$(cat "$CONTAINER_STATE_FILE")" = $'gpu=1\nmem-limit=2048m' ]
}
