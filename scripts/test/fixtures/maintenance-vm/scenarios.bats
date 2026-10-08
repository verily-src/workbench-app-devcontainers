#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../../.." && pwd)"
    SOURCE_ROOT="${MAINTENANCE_SOURCE_ROOT:-${REPO_ROOT}}"
    FIXTURES="${BATS_TEST_DIRNAME}"
    export WORKBENCH_ROOT="${BATS_TEST_TMPDIR}/root"
    export WORKBENCH_CLOUD=gcp WORKBENCH_MODE=runtime
    STATE_DIR="${WORKBENCH_ROOT}/var/lib/workbench-maintenance"
    PAYLOAD="${WORKBENCH_ROOT}/usr/lib/workbench/maintenance"
    SPIKE="${STATE_DIR}/spike"
    mkdir -p "${WORKBENCH_ROOT}/usr/lib/workbench" "${WORKBENCH_ROOT}/usr/lib/systemd/system/workbench"
    cp -R "${SOURCE_ROOT}/startupscript/butane" "${WORKBENCH_ROOT}/usr/lib/workbench/butane"
    cp -R "${SOURCE_ROOT}/startupscript/maintenance" "${PAYLOAD}"
    cp -R "${SOURCE_ROOT}/startupscript/maintenance/units/"* "${WORKBENCH_ROOT}/usr/lib/systemd/system/workbench/"
    cp "${FIXTURES}/actions/"*.sh "${PAYLOAD}/actions/"
}

scenario() {
    cp "${FIXTURES}/$1.json" "${PAYLOAD}/actions.json"
    run bash "${PAYLOAD}/run-actions.sh" "${PAYLOAD}/actions.json" "${STATE_DIR}"
    if [[ "$status" -ne 0 ]]; then printf '%s\n' "$output" | sed 's/^/# /' >&3; fi
}

@test "scenario declarations keep action identity and migration bytes unchanged" {
    local actual expected
    actual="$(sha256sum "${PAYLOAD}/actions/link-host-files.sh")"
    expected="$(cut -d ' ' -f 1 "${FIXTURES}/link-host-files.sha256")"
    [ "${actual%% *}" = "${expected}" ]
    jq -se '[.[].actions[]] | group_by(.id) | all(.[]; (unique | length) == 1)' "${FIXTURES}/"*.json
    jq -se 'all(.[]; any(.actions[]; .id == "link-host-files" and
        .script == "actions/link-host-files.sh" and .required and .depends_on == [] and .replaces == []))' "${FIXTURES}/"*.json
    cmp "${FIXTURES}/v3.json" "${FIXTURES}/rollback.json"
}

@test "v1 to v3 runs the missed action before third and keeps once at one attempt" {
    scenario v1
    [ "$status" -eq 0 ]
    [ "$(cat "${SPIKE}/once")" = 1 ]
    [ ! -e "${SPIKE}/skipped" ]
    scenario v3
    [ "$status" -eq 0 ]
    scenario v3
    [ "$status" -eq 0 ]
    local marker
    for marker in once skipped third; do
        [ "$(cat "${SPIKE}/${marker}")" = 1 ]
        [ "$(wc -l < "${SPIKE}/${marker}" | tr -d ' ')" = 1 ]
    done
    jq -e 'all(.actions[]; .status == "succeeded" and .attempts == 1)' "${STATE_DIR}/state.json"
    [ -L "${WORKBENCH_ROOT}/home/core/install-node.sh" ]
}

@test "required failure isolates the dependent and recovery satisfies the failed action" {
    scenario v3
    [ "$status" -eq 0 ]
    scenario failure
    [ "$status" -ne 0 ]
    [ "$(cat "${SPIKE}/independent")" = 1 ]
    [ ! -e "${SPIKE}/dependent" ]
    jq -e '.actions["spike-failure"].status == "failed" and
        .actions["spike-failure"].last_error == "exit status 42" and
        .actions["spike-dependent"] == null and .actions["spike-independent"].status == "succeeded"' "${STATE_DIR}/state.json"
    scenario recovery
    [ "$status" -eq 0 ]
    [ "$(cat "${SPIKE}/recovery")" = 1 ]
    [ "$(cat "${SPIKE}/dependent")" = 1 ]
    jq -e '.actions["spike-failure"].status == "replaced" and
        .actions["spike-failure"].replaced_by == "spike-recovery" and
        all(.actions[]; .attempts == 1)' "${STATE_DIR}/state.json"
    scenario rollback
    [ "$status" -eq 0 ]
    jq -e 'all(.actions[]; .attempts == 1)' "${STATE_DIR}/state.json"
}

@test "marker retries preserve a completed result after an interrupted write" {
    mkdir -p "${SPIKE}"
    printf partial > "${SPIKE}/.once.interrupted"
    local attempt
    for attempt in 1 2; do
        WORKBENCH_MAINTENANCE_STATE_DIR="${STATE_DIR}" WORKBENCH_MAINTENANCE_ACTION_ID=spike-once \
            bash "${FIXTURES}/actions/spike-marker.sh"
    done
    [ "$(cat "${SPIKE}/once")" = 1 ]
    [ "$(wc -l < "${SPIKE}/once" | tr -d ' ')" = 1 ]
}
