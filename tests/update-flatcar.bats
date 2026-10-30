#!/usr/bin/env bats
# Test suite for update-flatcar.sh. Host binaries are replaced with stubs on PATH and the script's
# absolute paths are rewritten into a per-test temp directory.

readonly VERSION_URL="https://workbench-test.verily.com/api/app/version"
readonly UPDATE_CONF=$'REBOOT_STRATEGY=off\nSERVER=disabled\n'
readonly CLEAR=$'metadata os_update/reboot_required=\nmetadata os_update/timestamp=\n'
readonly UPDATE=$'flatcar-update --to-version 4593.2.10 --disable-afterwards\n'
readonly RESET=$'cgpt prioritize /dev/sda4\nreset\n'
readonly INSTALLED="Installed Flatcar version: 4593.2.5"
readonly APPROVED="Approved Flatcar version: 4593.2.10"
readonly NOT_OLDER="Installed version is not older than approved; skipping"
readonly NO_PIN="Could not read the approved Flatcar version from ${VERSION_URL}"
readonly STAGING=$'Updating Flatcar from 4593.2.5 to 4593.2.10\nStaged Flatcar 4593.2.10; it applies on the next reboot'

setup() {
    DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" >/dev/null 2>&1 && pwd)"
    REPO_ROOT="$(cd "${DIR}/.." && pwd)"
    ROOT="${BATS_TEST_TMPDIR}"
    mkdir -p "${ROOT}/bin"

    CURRENT_VERSION="4593.2.5"
    GROUP_CONF=""
    ENGINE_STATE="UPDATE_STATUS_IDLE"
    STAGED_VERSION=""
    PIN='{"flatcar_stable_version":"4593.2.10"}'
    STATUS_EXIT=0
    CURL_EXIT=0
    UPDATE_EXIT=0
    FLOCK_EXIT=0
    ROOTDEV_EXIT=0
    CGPT_EXIT=0

    printf '%s' "${UPDATE_CONF}" > "${ROOT}/update.conf"
    : > "${ROOT}/actions"
    cat > "${ROOT}/metadata-utils.sh" <<'EOF'
set_metadata() { printf 'metadata %s=%s\n' "$1" "$2" >> "$TEST_ROOT/actions"; }
EOF
    stub flock 'exit "${FLOCK_EXIT:-0}"'
    stub rootdev '
[[ "${ROOTDEV_EXIT:-0}" == 0 ]] || exit "$ROOTDEV_EXIT"
[[ "$*" == "-s /usr" ]] || exit 99
echo /dev/sda4'
    stub cgpt '
echo "cgpt $*" >> "$TEST_ROOT/actions"
exit "${CGPT_EXIT:-0}"'
    stub update_engine_client '
case "$*" in
  -status)
    [[ "${STATUS_EXIT:-0}" == 0 ]] || exit "$STATUS_EXIT"
    [[ -f "$TEST_ROOT/engine_state" ]] && ENGINE_STATE="$(cat "$TEST_ROOT/engine_state")"
    printf "CURRENT_OP=%s\nNEW_VERSION=%s\n" "$ENGINE_STATE" "$STAGED_VERSION"
    ;;
  -reset_status)
    echo reset >> "$TEST_ROOT/actions"
    echo UPDATE_STATUS_IDLE > "$TEST_ROOT/engine_state"
    ;;
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
    stub reboot "echo 'unexpected reboot' >> \"\$TEST_ROOT/actions\"; exit 99"
    stub systemctl '
if [[ "$*" == "try-restart locksmithd.service" ]]; then
  echo restarted >> "$TEST_ROOT/locksmithd"
  exit 0
fi
echo "unexpected systemctl $*" >> "$TEST_ROOT/actions"
exit 99'

    sed -e "s#/usr/share/flatcar/os-release#${ROOT}/os-release#g" \
        -e "s#/usr/share/flatcar/update.conf#${ROOT}/share-update.conf#g" \
        -e "s#/home/core/metadata-utils.sh#${ROOT}/metadata-utils.sh#g" \
        -e "s#/run/lock/update-flatcar.lock#${ROOT}/update-flatcar.lock#g" \
        -e "s#/etc/flatcar/update.conf#${ROOT}/update.conf#g" \
        "${REPO_ROOT}/startupscript/butane/update-flatcar.sh" > "${ROOT}/update-flatcar.sh"
}

stub() {
    printf '#!/bin/bash\n%s\n' "$2" > "${ROOT}/bin/$1"
    chmod +x "${ROOT}/bin/$1"
}

run_update() {
    printf 'VERSION_ID=%s\n' "${CURRENT_VERSION}" > "${ROOT}/os-release"
    printf '%s' "${PIN}" > "${ROOT}/pin.json"
    printf '%s\n' "${GROUP_CONF:-GROUP=stable}" > "${ROOT}/share-update.conf"
    run env PATH="${ROOT}/bin:${PATH}" TEST_ROOT="${ROOT}" \
        ENGINE_STATE="${ENGINE_STATE}" STAGED_VERSION="${STAGED_VERSION}" \
        STATUS_EXIT="${STATUS_EXIT}" CURL_EXIT="${CURL_EXIT}" \
        UPDATE_EXIT="${UPDATE_EXIT}" FLOCK_EXIT="${FLOCK_EXIT}" \
        ROOTDEV_EXIT="${ROOTDEV_EXIT}" CGPT_EXIT="${CGPT_EXIT}" \
        bash "${ROOT}/update-flatcar.sh" "${VERSION_URL}"
}

# usage: lines <line>...
lines() {
    local IFS=$'\n'
    echo "$*"
}

# usage: expect <success|failure> <actions> [output]
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
    if [[ $# -ge 3 && "${output}" != "$3" ]]; then
        echo "output = $(printf '%q' "${output}"), want $(printf '%q' "$3")"
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
    expect success "${CLEAR}" "$(lines "${INSTALLED}" "Approved Flatcar version: 4593.2.5" "${NOT_OLDER}")"
}

@test "newer version" {
    run_update
    expect success "${CLEAR}${UPDATE}" "$(lines "${INSTALLED}" "${APPROVED}" "${STAGING}")"
}

@test "matching staged version" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4593.2.10"
    run_update
    expect success "" "$(lines "${INSTALLED}" "${APPROVED}" "Approved version is already staged; skipping until reboot")"
}

@test "obsolete staged version" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    run_update
    expect success "${RESET}${UPDATE}" "$(lines "${INSTALLED}" "${APPROVED}" \
        "Canceling staged 4757.2.0; approved version is 4593.2.10" "${STAGING}")"
}

@test "rollback without staged update" {
    CURRENT_VERSION="4757.2.0"
    run_update
    expect success "${CLEAR}" "$(lines "Installed Flatcar version: 4757.2.0" "${APPROVED}" "${NOT_OLDER}")"
}

@test "rollback cancels staged update" {
    CURRENT_VERSION="4757.2.0"
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4790.1.0"
    run_update
    expect success "${RESET}${CLEAR}" "$(lines "Installed Flatcar version: 4757.2.0" "${APPROVED}" \
        "Canceling staged 4790.1.0; approved version is not newer than installed")"
}

@test "same version cancels staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${RESET}${CLEAR}" "$(lines "${INSTALLED}" "Approved Flatcar version: 4593.2.5" \
        "Canceling staged 4757.2.0; approved version is not newer than installed")"
}

@test "status failure" {
    STATUS_EXIT=1
    run_update
    expect failure "" ""
}

@test "unknown status" {
    ENGINE_STATE="unexpected"
    run_update
    expect failure "" $'Unexpected update engine status: CURRENT_OP=unexpected\nNEW_VERSION='
}

@test "curl failure" {
    CURL_EXIT=22
    run_update
    expect failure "${CLEAR}" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "curl failure with staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    CURL_EXIT=22
    run_update
    expect failure "" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "missing pin" {
    PIN='{}'
    run_update
    expect failure "${CLEAR}" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "missing pin with staged update" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{}'
    run_update
    expect failure "" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "null pin" {
    PIN='{"flatcar_stable_version":null}'
    run_update
    expect failure "${CLEAR}" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "non-string pin" {
    PIN='{"flatcar_stable_version":4593}'
    run_update
    expect failure "${CLEAR}" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "malformed pin" {
    PIN='{"flatcar_stable_version":"4593.2.10;reboot"}'
    run_update
    expect failure "${CLEAR}" "$(lines "${INSTALLED}" "${NO_PIN}")"
}

@test "malformed JSON" {
    PIN='{'
    run_update
    expect failure "${CLEAR}"
}

@test "invalid running version" {
    CURRENT_VERSION="invalid"
    run_update
    expect failure "" "Invalid running Flatcar version: invalid"
}

@test "busy update engine states are left alone" {
    for state in UPDATE_STATUS_CHECKING_FOR_UPDATE UPDATE_STATUS_UPDATE_AVAILABLE \
        UPDATE_STATUS_DOWNLOADING UPDATE_STATUS_VERIFYING UPDATE_STATUS_FINALIZING \
        UPDATE_STATUS_REPORTING_ERROR_EVENT; do
        ENGINE_STATE="${state}"
        run_update
        expect success "" "update-engine is busy (${state}); skipping" || { echo "state ${state}"; return 1; }
    done
}

@test "lock held" {
    FLOCK_EXIT=1
    run_update
    expect success "" "Another update check holds the lock; skipping"
}

@test "update failure" {
    UPDATE_EXIT=1
    run_update
    expect failure "${CLEAR}${UPDATE}" "$(lines "${INSTALLED}" "${APPROVED}" "Updating Flatcar from 4593.2.5 to 4593.2.10")"
}

@test "non-stable GROUP is refused" {
    GROUP_CONF="GROUP=beta"
    run_update
    expect failure "" "Booted channel is 'beta'; only stable is pinned"
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

@test "failed boot-priority restore keeps the reboot notice" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    CGPT_EXIT=1
    run_update
    expect failure $'cgpt prioritize /dev/sda4\n' "$(lines "${INSTALLED}" "Approved Flatcar version: 4593.2.5" \
        "Canceling staged 4757.2.0; approved version is not newer than installed")"
}

@test "failed boot-priority restore is retried on the next poll" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    CGPT_EXIT=1
    run_update
    CGPT_EXIT=0
    run_update
    expect success $'cgpt prioritize /dev/sda4\n'"${RESET}${CLEAR}"
}

@test "unknown running partition leaves the staged update alone" {
    ENGINE_STATE="UPDATE_STATUS_UPDATED_NEED_REBOOT"
    STAGED_VERSION="4757.2.0"
    ROOTDEV_EXIT=1
    run_update
    expect failure ""
}

@test "restores a missing SERVER line" {
    printf 'REBOOT_STRATEGY=off\n' > "${ROOT}/update.conf"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${CLEAR}"
}

@test "restores SERVER even when the pin lookup fails" {
    printf 'REBOOT_STRATEGY=off\nSERVER=https://public.update.flatcar-linux.net/v1/update/\n' > "${ROOT}/update.conf"
    CURL_EXIT=22
    run_update
    expect failure "${CLEAR}"
}

@test "replaces a NUL-corrupted update.conf" {
    printf 'REBOOT_STRATEGY=off\n\0\0\0\0' > "${ROOT}/update.conf"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${CLEAR}"
}

@test "recreates a missing update.conf" {
    rm "${ROOT}/update.conf"
    PIN='{"flatcar_stable_version":"4593.2.5"}'
    run_update
    expect success "${CLEAR}"
}

@test "restores SERVER on a VM the channel check refuses" {
    printf 'REBOOT_STRATEGY=off\n' > "${ROOT}/update.conf"
    GROUP_CONF="GROUP=beta"
    run_update
    expect failure ""
}

@test "restarts locksmithd so it rereads the reboot strategy" {
    run_update
    expect success "${CLEAR}${UPDATE}"
    grep -q restarted "${ROOT}/locksmithd" || { echo "locksmithd not restarted"; return 1; }
}
