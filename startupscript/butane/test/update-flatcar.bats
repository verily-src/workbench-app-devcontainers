#!/usr/bin/env bats
# Test suite for update-flatcar.sh. Host binaries are replaced with stubs on PATH and the script's
# absolute paths are rewritten into a per-test temp directory.

readonly VERSION_URL="https://workbench-test.verily.com/api/app/version"
readonly UPDATE_CONF=$'REBOOT_STRATEGY=off\nSERVER=disabled\n'
readonly CLEAR=$'metadata os_update/reboot_required=\nmetadata os_update/timestamp=\n'
readonly UPDATE=$'flatcar-update --to-version 4593.2.10 --disable-afterwards\n'
readonly RESET=$'reset\n'

setup() {
    DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" >/dev/null 2>&1 && pwd)"
    ROOT="${BATS_TEST_TMPDIR}"
    mkdir -p "${ROOT}/bin"

    CURRENT_VERSION="4593.2.5"
    CHANNEL="stable"
    GROUP_CONF=""
    ENGINE_STATE="UPDATE_STATUS_IDLE"
    STAGED_VERSION=""
    PIN='{"flatcar_stable_version":"4593.2.10"}'
    STATUS_EXIT=0
    CURL_EXIT=0
    UPDATE_EXIT=0
    FLOCK_EXIT=0

    printf '%s' "${UPDATE_CONF}" > "${ROOT}/update.conf"
    : > "${ROOT}/actions"
    cat > "${ROOT}/metadata-utils.sh" <<'EOF'
set_metadata() { printf 'metadata %s=%s\n' "$1" "$2" >> "$TEST_ROOT/actions"; }
EOF
    stub flock 'exit "${FLOCK_EXIT:-0}"'
    stub update_engine_client '
case "$*" in
  -status)
    [[ "${STATUS_EXIT:-0}" == 0 ]] || exit "$STATUS_EXIT"
    printf "CURRENT_OP=%s\nNEW_VERSION=%s\n" "$ENGINE_STATE" "$STAGED_VERSION"
    ;;
  -reset_status) echo reset >> "$TEST_ROOT/actions" ;;
  *) echo "unexpected update_engine_client $*" >> "$TEST_ROOT/actions"; exit 99 ;;
esac'
    stub curl '
[[ "${CURL_EXIT:-0}" == 0 ]] || exit "$CURL_EXIT"
[[ "${!#}" == '"${VERSION_URL}"' ]] || exit 99
cat "$TEST_ROOT/pin.json"'
    stub flatcar-update '
echo "flatcar-update $*" >> "$TEST_ROOT/actions"
printf "REBOOT_STRATEGY=off\nSERVER=https://update.flatcar-linux.net/v1/update/\n" > "$TEST_ROOT/update.conf"
exit "${UPDATE_EXIT:-0}"'
    for name in reboot systemctl; do
        stub "${name}" "echo 'unexpected ${name}' >> \"\$TEST_ROOT/actions\"; exit 99"
    done
    if [[ "$(uname)" == Darwin ]]; then
        stub sed 'if [[ $1 == -i ]]; then shift; exec /usr/bin/sed -i "" "$@"; fi; exec /usr/bin/sed "$@"'
    fi

    sed -e "s#/usr/share/flatcar/os-release#${ROOT}/os-release#g" \
        -e "s#/usr/share/flatcar/update.conf#${ROOT}/share-update.conf#g" \
        -e "s#/home/core/metadata-utils.sh#${ROOT}/metadata-utils.sh#g" \
        -e "s#/run/lock/update-flatcar.lock#${ROOT}/update-flatcar.lock#g" \
        -e "s#/etc/flatcar/update.conf#${ROOT}/update.conf#g" \
        "${DIR}/../update-flatcar.sh" > "${ROOT}/update-flatcar.sh"
}

stub() {
    printf '#!/bin/bash\n%s\n' "$2" > "${ROOT}/bin/$1"
    chmod +x "${ROOT}/bin/$1"
}

run_update() {
    printf 'VERSION_ID=%s\n' "${CURRENT_VERSION}" > "${ROOT}/os-release"
    printf '%s' "${PIN}" > "${ROOT}/pin.json"
    printf '%s\n' "${GROUP_CONF:-GROUP=${CHANNEL}}" > "${ROOT}/share-update.conf"
    run env PATH="${ROOT}/bin:${PATH}" TEST_ROOT="${ROOT}" \
        ENGINE_STATE="${ENGINE_STATE}" STAGED_VERSION="${STAGED_VERSION}" \
        STATUS_EXIT="${STATUS_EXIT}" CURL_EXIT="${CURL_EXIT}" \
        UPDATE_EXIT="${UPDATE_EXIT}" FLOCK_EXIT="${FLOCK_EXIT}" \
        bash "${ROOT}/update-flatcar.sh" "${VERSION_URL}" "${CHANNEL}"
}

# usage: expect <success|failure> <actions>
expect() {
    if [[ "$1" == success && "${status}" -ne 0 ]] || [[ "$1" == failure && "${status}" -eq 0 ]]; then
        echo "status ${status}, want $1; output: ${output}"
        return 1
    fi
    local actions
    actions="$(cat "${ROOT}/actions"; echo x)"
    actions="${actions%x}"
    if [[ "${actions}" != "$2" ]]; then
        echo "actions = $(printf '%q' "${actions}"), want $(printf '%q' "$2"); output: ${output}"
        return 1
    fi
    local conf
    conf="$(cat "${ROOT}/update.conf"; echo x)"
    conf="${conf%x}"
    if [[ "${conf}" != "${UPDATE_CONF}" ]]; then
        echo "update.conf = $(printf '%q' "${conf}"), want $(printf '%q' "${UPDATE_CONF}")"
        return 1
    fi
}

@test "same version" {
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${CLEAR}${CLEAR}"
}

@test "newer version" {
    run_update
    expect success "${CLEAR}${UPDATE}"
}

@test "beta channel" {
    CHANNEL="beta"
    PIN='{"flatcar_stable_version":"4593.2.5","flatcar_beta_version":"4593.2.10"}'
    run_update
    expect success "${CLEAR}${UPDATE}"
}

@test "matching staged version" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4593.2.10"
    run_update
    expect success ""
}

@test "obsolete staged version" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    run_update
    expect success "${RESET}${CLEAR}${UPDATE}"
}

@test "rollback without staged update" {
    CURRENT_VERSION="4757.2.0"
    run_update
    expect success "${CLEAR}${CLEAR}"
}

@test "rollback cancels staged update" {
    CURRENT_VERSION="4757.2.0"
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4790.1.0"
    run_update
    expect success "${RESET}${CLEAR}"
}

@test "same version cancels staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${RESET}${CLEAR}"
}

@test "status failure" {
    STATUS_EXIT=1
    run_update
    expect failure ""
}

@test "unknown status" {
    ENGINE_STATE="unexpected"
    run_update
    expect failure ""
}

@test "curl failure" {
    CURL_EXIT=22
    run_update
    expect failure "${CLEAR}"
}

@test "curl failure with staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    CURL_EXIT=22
    run_update
    expect failure ""
}

@test "missing pin" {
    PIN='{}'
    run_update
    expect failure "${CLEAR}"
}

@test "missing pin with staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{}'
    run_update
    expect failure ""
}

@test "null pin" {
    PIN='{"flatcar_stable_version":null}'
    run_update
    expect failure "${CLEAR}"
}

@test "non-string pin" {
    PIN='{"flatcar_stable_version":4593}'
    run_update
    expect failure "${CLEAR}"
}

@test "malformed pin" {
    PIN='{"flatcar_stable_version":"4593.2.10;reboot"}'
    run_update
    expect failure "${CLEAR}"
}

@test "malformed JSON" {
    PIN='{'
    run_update
    expect failure "${CLEAR}"
}

@test "invalid running version" {
    CURRENT_VERSION="invalid"
    run_update
    expect failure "${CLEAR}"
}

@test "busy update engine states are left alone" {
    for state in UPDATE_STATUS_CHECKING_FOR_UPDATE UPDATE_STATUS_UPDATE_AVAILABLE \
        UPDATE_STATUS_DOWNLOADING UPDATE_STATUS_VERIFYING UPDATE_STATUS_FINALIZING \
        UPDATE_STATUS_REPORTING_ERROR_EVENT UPDATE_STATUS_ATTEMPTING_ROLLBACK; do
        ENGINE_STATE="${state}"
        run_update
        expect success "" || { echo "state ${state}"; return 1; }
    done
}

@test "lock held" {
    FLOCK_EXIT=1
    run_update
    expect success ""
}

@test "update failure" {
    UPDATE_EXIT=1
    run_update
    expect failure "${CLEAR}${UPDATE}"
}

@test "GROUP disagrees with argument" {
    GROUP_CONF="GROUP=beta"
    PIN='{"flatcar_beta_version":"4593.2.10"}'
    run_update
    expect success "${CLEAR}${UPDATE}"
}

@test "GROUP missing" {
    GROUP_CONF="SERVER=disabled"
    run_update
    expect failure ""
}

@test "GROUP invalid" {
    GROUP_CONF="GROUP=nightly"
    run_update
    expect failure ""
}

@test "unsupported channel argument" {
    CHANNEL="nightly"
    GROUP_CONF="GROUP=stable"
    run_update
    expect failure ""
}
