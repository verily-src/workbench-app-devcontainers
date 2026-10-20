#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    RUNNER="$REPO_ROOT/startupscript/maintenance/run-actions.sh"
    MANIFEST="$BATS_TEST_TMPDIR/payload/actions.json"
    STATE_DIR="$BATS_TEST_TMPDIR/state"
    export CALLS="$BATS_TEST_TMPDIR/calls"
    mkdir -p "$(dirname "$MANIFEST")/actions"
    printf '%s\n' '{"schema":1,"actions":[]}' > "$MANIFEST"
    : > "$CALLS"
}

add_action() {
    local id="$1" dependencies="${2:-[]}" required="${3:-true}" replaces="${4:-[]}"
    jq --arg id "$id" --argjson dependencies "$dependencies" --argjson required "$required" \
        --argjson replaces "$replaces" '.actions += [{id:$id,script:("actions/"+$id+".sh"),
        depends_on:$dependencies,required:$required,replaces:$replaces}]' "$MANIFEST" > "$MANIFEST.tmp"
    mv "$MANIFEST.tmp" "$MANIFEST"
    cat > "$(dirname "$MANIFEST")/actions/$id.sh" <<'SCRIPT'
echo "$WORKBENCH_MAINTENANCE_ACTION_ID" >> "$CALLS"
[[ "${FAIL_ACTION:-}" != "$WORKBENCH_MAINTENANCE_ACTION_ID" ]]
SCRIPT
}

run_actions() {
    run bash "$RUNNER" "$MANIFEST" "$STATE_DIR"
}

@test "successful actions execute once in dependency order across releases" {
    add_action a '["z"]'
    add_action z
    run_actions
    [ "$status" -eq 0 ]
    [ "$(cat "$CALLS")" = $'z\na' ]
    add_action skipped_release '["a"]'
    add_action current_release '["skipped_release"]'
    run_actions
    [ "$status" -eq 0 ]
    [ "$(cat "$CALLS")" = $'z\na\nskipped_release\ncurrent_release' ]
    jq -e 'all(.actions[]; .status == "succeeded" and .attempts == 1)' "$STATE_DIR/state.json"
}

@test "failure blocks dependents while independent actions finish and retry succeeds" {
    add_action failure
    add_action dependent '["failure"]'
    add_action independent
    export FAIL_ACTION=failure
    run_actions
    [ "$status" -ne 0 ]
    [ "$(cat "$CALLS")" = $'failure\nindependent' ]
    jq -e '.actions.failure.status == "failed" and .actions.dependent == null and
        .actions.independent.status == "succeeded"' "$STATE_DIR/state.json"
    unset FAIL_ACTION
    run_actions
    [ "$status" -eq 0 ]
    [ "$(cat "$CALLS")" = $'failure\nindependent\nfailure\ndependent' ]
    jq -e '.actions.failure.attempts == 2 and .actions.independent.attempts == 1' "$STATE_DIR/state.json"
}

@test "optional failure does not block startup unless a required action depends on it" {
    add_action optional '[]' false
    export FAIL_ACTION=optional
    run_actions
    [ "$status" -eq 0 ]
    add_action required '["optional"]'
    run_actions
    [ "$status" -ne 0 ]
    jq -e '.actions.required == null' "$STATE_DIR/state.json"
}

@test "a successful replacement satisfies the old required action and its dependents" {
    add_action old
    add_action dependent '["old"]'
    export FAIL_ACTION=old
    run_actions
    [ "$status" -ne 0 ]
    add_action replacement '[]' false '["old"]'
    run_actions
    [ "$status" -eq 0 ]
    [ "$(cat "$CALLS")" = $'old\nreplacement\ndependent' ]
    jq -e '.actions.old.status == "replaced" and .actions.old.replaced_by == "replacement" and
        .actions.old.attempts == 1 and .actions.replacement.status == "succeeded"' "$STATE_DIR/state.json"
}

@test "failed replacements keep required obligations and dependents blocked" {
    add_action old
    add_action dependent '["old"]'
    add_action replacement '[]' false '["old"]'
    export FAIL_ACTION=replacement
    run_actions
    [ "$status" -ne 0 ]
    [ "$(cat "$CALLS")" = replacement ]
    jq -e '.actions.old == null and .actions.dependent == null and
        .actions.replacement.status == "failed"' "$STATE_DIR/state.json"
}

@test "a replacement can replace a failed replacement across skipped releases" {
    add_action old
    add_action dependent '["old"]'
    add_action first_replacement '[]' false '["old"]'
    export FAIL_ACTION=first_replacement
    run_actions
    [ "$status" -ne 0 ]
    add_action latest_replacement '[]' false '["first_replacement"]'
    run_actions
    [ "$status" -eq 0 ]
    [ "$(cat "$CALLS")" = $'first_replacement\nlatest_replacement\ndependent' ]
    jq -e '.actions.old.status == "replaced" and .actions.old.replaced_by == "latest_replacement" and
        .actions.first_replacement.status == "replaced"' "$STATE_DIR/state.json"
}

@test "executed IDs reject changed bytes before any other action runs" {
    add_action old
    run_actions
    [ "$status" -eq 0 ]
    printf '\necho changed\n' >> "$(dirname "$MANIFEST")/actions/old.sh"
    add_action new
    run_actions
    [ "$status" -ne 0 ]
    [[ "$output" == *'changed after being recorded'* ]]
    [ "$(cat "$CALLS")" = old ]
}

@test "manifest rejects unknown references duplicate IDs and invalid types before actions" {
    add_action safe
    cp "$MANIFEST" "$BATS_TEST_TMPDIR/original.json"
    local change
    for change in '.actions[0].depends_on=["unknown"]' '.actions += [.actions[0]]' \
        '.actions[0].required="true"' '.actions[0].id="bad/id"' '.schema=2' \
        '.actions[0].replaces=["unknown"]'; do
        jq "$change" "$BATS_TEST_TMPDIR/original.json" > "$MANIFEST"
        run_actions
        [ "$status" -ne 0 ]
        [ ! -s "$CALLS" ]
    done
}

@test "manifest rejects dependency replacement and mixed cycles before actions" {
    add_action a
    add_action b
    cp "$MANIFEST" "$BATS_TEST_TMPDIR/original.json"
    local change
    for change in '.actions[0].depends_on=["b"] | .actions[1].depends_on=["a"]' \
        '.actions[0].replaces=["b"] | .actions[1].replaces=["a"]' \
        '.actions[1].depends_on=["a"] | .actions[1].replaces=["a"]'; do
        jq "$change" "$BATS_TEST_TMPDIR/original.json" > "$MANIFEST"
        run_actions
        [ "$status" -ne 0 ]
        [ ! -s "$CALLS" ]
    done
}

@test "multiple replacements for one action are rejected" {
    add_action old
    add_action first '[]' true '["old"]'
    add_action second '[]' true '["old"]'
    run_actions
    [ "$status" -ne 0 ]
    [ ! -s "$CALLS" ]
}

@test "scripts cannot escape the manifest directory through paths or symlinks" {
    add_action safe
    cp "$(dirname "$MANIFEST")/actions/safe.sh" "$BATS_TEST_TMPDIR/outside.sh"
    rm "$(dirname "$MANIFEST")/actions/safe.sh"
    ln -s "$BATS_TEST_TMPDIR/outside.sh" "$(dirname "$MANIFEST")/actions/safe.sh"
    run_actions
    [ "$status" -ne 0 ]
    [ ! -s "$CALLS" ]
    jq '.actions[0].script="../../outside.sh"' "$MANIFEST" > "$MANIFEST.tmp"
    mv "$MANIFEST.tmp" "$MANIFEST"
    run_actions
    [ "$status" -ne 0 ]
    [ ! -s "$CALLS" ]
}

@test "corrupt state fails closed without overwriting it" {
    add_action safe
    mkdir -p "$STATE_DIR"
    printf 'broken' > "$STATE_DIR/state.json"
    run_actions
    [ "$status" -ne 0 ]
    [ "$(cat "$STATE_DIR/state.json")" = broken ]
    [ ! -s "$CALLS" ]
}

@test "interrupted action leaves an atomic retryable failure record" {
    add_action interrupted
    cat > "$(dirname "$MANIFEST")/actions/interrupted.sh" <<'SCRIPT'
if [[ ! -e "$WORKBENCH_MAINTENANCE_STATE_DIR/attempted" ]]; then
    touch "$WORKBENCH_MAINTENANCE_STATE_DIR/attempted"
    kill -KILL "$PPID"
else
    echo recovered >> "$CALLS"
fi
SCRIPT
    run_actions
    [ "$status" -ne 0 ]
    jq -e '.actions.interrupted.status == "failed" and
        .actions.interrupted.last_error == "interrupted"' "$STATE_DIR/state.json"
    run_actions
    [ "$status" -eq 0 ]
    jq -e '.actions.interrupted.status == "succeeded" and .actions.interrupted.attempts == 2' "$STATE_DIR/state.json"
    [ "$(cat "$CALLS")" = recovered ]
}

@test "a held lock prevents another runner from executing actions" {
    add_action safe
    mkdir -p "$STATE_DIR"
    exec 8>"$STATE_DIR/.lock"
    flock --nonblock 8
    run_actions
    [ "$status" -ne 0 ]
    [[ "$output" == *'already running'* ]]
    [ ! -s "$CALLS" ]
    exec 8>&-
}
