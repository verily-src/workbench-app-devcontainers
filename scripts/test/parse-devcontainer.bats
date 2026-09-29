#!/usr/bin/env bats
# State migration and failure cases; full parser lifecycles are tested in integration/.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    export CONTAINER_STATE_FILE="$BATS_TEST_TMPDIR/container-state"
    export DEVCONTAINER_PATH="$BATS_TEST_TMPDIR/app"
    export CALLS="$BATS_TEST_TMPDIR/calls"
    : > "$CALLS"
    LOOKUP="docker ps -aq --no-trunc --filter label=devcontainer.local_folder=$DEVCONTAINER_PATH"
    REMOVAL="$LOOKUP
docker rm -f backend"
    sed -n '/^handle_container_state_changed() {/,/^}/p' \
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
            *) return 1 ;;
        esac
    }
    export -f docker
}

state_changed() {
    bash -euo pipefail -c 'source "$1"; shift; handle_container_state_changed "$@"' \
        bash "$BATS_TEST_TMPDIR/function.sh" "$@"
}

@test "older state files recreate once for a missing memory key, including an empty limit" {
    local limit
    for limit in '' 1024m; do
        printf '%s\n' 'gpu=1' 'shm-size=64m' > "$CONTAINER_STATE_FILE"
        : > "$CALLS"
        state_changed 'gpu=1' 'shm-size=64m' "mem-limit=$limit"
        state_changed 'gpu=1' 'shm-size=64m' "mem-limit=$limit"
        [ "$(cat "$CONTAINER_STATE_FILE")" = "$(printf '%s\n' 'gpu=1' 'shm-size=64m' "mem-limit=$limit")" ]
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

@test "failed state-file reads stop before looking up containers or overwriting state" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    # Invoked by the production function in the child shell.
    # shellcheck disable=SC2317
    sed() { return 2; }
    export -f sed
    run state_changed 'gpu=0'
    [ "$status" = 2 ]
    [ ! -s "$CALLS" ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=1' ]
}

@test "failed container lookup leaves state unchanged and retries successfully" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    LOOKUP_EXIT=1 run state_changed 'gpu=0'
    [ "$status" -ne 0 ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=1' ]
    [ "$(cat "$CALLS")" = "$LOOKUP" ]

    : > "$CALLS"
    state_changed 'gpu=0'
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=0' ]
    [ "$(cat "$CALLS")" = "$REMOVAL" ]
}

@test "failed container removal leaves state unchanged and retries successfully" {
    printf '%s\n' 'gpu=1' > "$CONTAINER_STATE_FILE"
    REMOVE_EXIT=1 run state_changed 'gpu=0'
    [ "$status" -ne 0 ]
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=1' ]
    [ "$(cat "$CALLS")" = "$REMOVAL" ]

    : > "$CALLS"
    state_changed 'gpu=0'
    [ "$(cat "$CONTAINER_STATE_FILE")" = 'gpu=0' ]
    [ "$(cat "$CALLS")" = "$REMOVAL" ]
}
