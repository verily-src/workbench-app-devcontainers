#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    WRAPPER="$REPO_ROOT/startupscript/butane/devcontainer.sh"
    export CONTAINER_STATE_FILE="${BATS_TEST_TMPDIR}/state"
    export POST_CREATE_DONE="$CONTAINER_STATE_FILE.d/setup/post-create.done"
    export FIXTURE="${BATS_TEST_TMPDIR}/app"
    export CALLS="${BATS_TEST_TMPDIR}/calls"
    export SNAPSHOT_FILE="${BATS_TEST_TMPDIR}/snapshot-image"
    export DEVCONTAINER_CLI="${BATS_TEST_TMPDIR}/bin/devcontainer"
    export PATH="${BATS_TEST_TMPDIR}/bin:$PATH"
    mkdir -p "$FIXTURE" "${BATS_TEST_TMPDIR}/bin" "$(dirname "$POST_CREATE_DONE")"
    touch "$POST_CREATE_DONE" "$SNAPSHOT_FILE"
    cat > "$FIXTURE/.devcontainer.json" <<'JSON'
{"dockerComposeFile":["docker-compose.yaml","docker-compose.build.yaml"],
 "service":"backend","runServices":["app","backend"],"workspaceFolder":"/workspace",
 "features":{"already-installed":{}},"postCreateCommand":"setup","postStartCommand":"startup",
 "customizations":{"workbench":{"AIRLOCK_ENABLED":true}}}
JSON
    printf '%s\n' backend > "${BATS_TEST_TMPDIR}/primary"
    export PRIMARY_FILE="${BATS_TEST_TMPDIR}/primary"
    cat > "$DEVCONTAINER_CLI" <<'SH'
#!/bin/bash
echo "cli $*" >> "$CALLS"
[[ "$1" != up || "${CLI_EXIT:-0}" != 0 ]] || echo backend > "$PRIMARY_FILE"
exit "${CLI_EXIT:-0}"
SH
    cat > "${BATS_TEST_TMPDIR}/bin/docker" <<'SH'
#!/bin/bash
set -e
echo "docker $*" >> "$CALLS"
case "$1" in
    ps) cat "$PRIMARY_FILE" ;;
    image) [[ "$2" == inspect && -f "$SNAPSHOT_FILE" ]] ;;
    commit)
        [[ -f "$POST_CREATE_DONE" && -s "$PRIMARY_FILE" && "${FAIL_COMMIT:-}" != "$2" ]] || exit 1
        touch "$SNAPSHOT_FILE"
        ;;
    *) exit 1 ;;
esac
SH
    # Tests are single-process; production uses flock on Linux.
    printf '#!/bin/bash\nexit 0\n' > "${BATS_TEST_TMPDIR}/bin/flock"
    chmod +x "${BATS_TEST_TMPDIR}/bin/"*
}

assert_no_call() {
    run grep -E "$1" "$CALLS"
    [ "$status" = 1 ]
}

@test "initial up clears stale completion and snapshots the initialized backend once" {
    : > "$PRIMARY_FILE"
    rm "$SNAPSHOT_FILE"
    "$WRAPPER" build "$FIXTURE"
    [ ! -f "$POST_CREATE_DONE" ]
    grep -q '^cli build ' "$CALLS"
    assert_no_call '^docker commit '
    "$WRAPPER" up "$FIXTURE"
    [ -f "$POST_CREATE_DONE" ]
    [ -f "$SNAPSHOT_FILE" ]
    [ -s "$PRIMARY_FILE" ]
    [ "$(grep -E '^(cli up|docker commit)' "$CALLS")" = "cli up --workspace-folder $FIXTURE --user-data-folder $CONTAINER_STATE_FILE.d/cli
docker commit backend workbench-local-snapshot:devcontainer" ]
    "$WRAPPER" up "$FIXTURE"
    [ "$(grep -c '^docker commit ' "$CALLS")" = 1 ]
}

@test "failed restore retries the initial snapshot without building or committing" {
    : > "$PRIMARY_FILE"
    "$WRAPPER" build "$FIXTURE"
    jq -e '.dockerComposeFile == "docker-compose.yaml" and .runServices == [.service] and
        .customizations.workbench.AIRLOCK_ENABLED == true and
        (has("features") | not) and (has("postStartCommand") | not)' "$FIXTURE/.devcontainer.json"
    run env CLI_EXIT=1 "$WRAPPER" up "$FIXTURE"
    [ "$status" -ne 0 ]
    [ ! -s "$PRIMARY_FILE" ]
    "$WRAPPER" build "$FIXTURE"
    "$WRAPPER" up "$FIXTURE"
    [ -s "$PRIMARY_FILE" ]
    assert_no_call '^cli build |^docker commit '
}

@test "a failed initial snapshot retains completed setup and retries on the next up" {
    : > "$PRIMARY_FILE"
    rm "$POST_CREATE_DONE" "$SNAPSHOT_FILE"
    run env FAIL_COMMIT=backend "$WRAPPER" up "$FIXTURE"
    [ "$status" -ne 0 ]
    [ -f "$POST_CREATE_DONE" ]
    [ ! -f "$SNAPSHOT_FILE" ]
    [ -s "$PRIMARY_FILE" ]
    assert_no_call '^docker (stop|rm) |application-server'
    "$WRAPPER" build "$FIXTURE"
    "$WRAPPER" up "$FIXTURE"
    [ -f "$SNAPSHOT_FILE" ]
    [ "$(grep -c '^docker commit ' "$CALLS")" = 2 ]
    assert_no_call '^cli build '
}

@test "failed initial startup records neither completion nor a snapshot until retry succeeds" {
    : > "$PRIMARY_FILE"
    rm "$POST_CREATE_DONE" "$SNAPSHOT_FILE"
    run env CLI_EXIT=1 "$WRAPPER" up "$FIXTURE"
    [ "$status" -ne 0 ]
    [ ! -f "$POST_CREATE_DONE" ]
    [ ! -f "$SNAPSHOT_FILE" ]
    assert_no_call '^docker commit '
    "$WRAPPER" up "$FIXTURE"
    [ -f "$POST_CREATE_DONE" ]
    [ -f "$SNAPSHOT_FILE" ]
    [ "$(grep -c '^docker commit ' "$CALLS")" = 1 ]
}

@test "non-airlock configs in either location ignore stale snapshots" {
    local config
    mv "$FIXTURE/.devcontainer.json" "$FIXTURE/original.json"
    mkdir "$FIXTURE/.devcontainer"
    for config in "$FIXTURE/.devcontainer.json" "$FIXTURE/.devcontainer/devcontainer.json"; do
        : > "$PRIMARY_FILE"
        : > "$CALLS"
        if [[ "$config" == "$FIXTURE/.devcontainer.json" ]]; then
            jq '.customizations.workbench.AIRLOCK_ENABLED = false' "$FIXTURE/original.json" > "$config"
        else
            jq 'del(.customizations)' "$FIXTURE/original.json" > "$config"
        fi
        cp "$config" "$FIXTURE/expected.json"
        "$WRAPPER" build "$FIXTURE"
        "$WRAPPER" up "$FIXTURE"
        grep -q '^cli build ' "$CALLS"
        grep -q '^cli up ' "$CALLS"
        assert_no_call '^docker image inspect |^docker commit '
        cmp "$FIXTURE/expected.json" "$config"
        [ ! -d "$CONTAINER_STATE_FILE.d/jupyter-home" ]
        rm "$config"
    done
}
