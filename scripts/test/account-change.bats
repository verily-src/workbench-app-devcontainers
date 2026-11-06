#!/usr/bin/env bats
# A VM whose service account changed since the last boot, as when its owner turns
# sharing on: the host logs the Workbench CLI out, and the app container clears
# the credentials cached in the home directory, logs in again and mounts buckets
# read-only for the reader account. The metadata server, the Workbench CLI, sudo,
# Docker and gcsfuse are stubbed on PATH.

OWNER=pet-1234@ws-project.iam.gserviceaccount.com
READER=shared-apps-reader@ws-project.iam.gserviceaccount.com
WRITER=shared-apps-writer@ws-project.iam.gserviceaccount.com

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    STARTUP="${REPO_ROOT}/startupscript"
    export TEST_ROOT="${BATS_TEST_TMPDIR}/root"
    export HOME_DIR="${TEST_ROOT}/home/jupyter"
    mkdir -p "${TEST_ROOT}/bin" "${HOME_DIR}/.workbench"
    touch "${TEST_ROOT}/wb-calls" "${TEST_ROOT}/curl-calls"

    stub curl '
url="${*: -1}"
echo "${url}" >> "${TEST_ROOT}/curl-calls"
case "${url}" in
    */instance/service-accounts/default/email)
        [[ -f "${TEST_ROOT}/email" ]] || exit 22; cat "${TEST_ROOT}/email" ;;
    */attributes/terra-cli-server) printf dev-stable ;;
    */attributes/terra-workspace-id) printf ws-ufid ;;
    *) echo "Unexpected curl URL: ${url}" >&2; exit 99 ;;
esac'
    # Runs the command as the test user: drops "-u <user>" and the login shell.
    stub sudo '
[[ "$1" == -u ]] && shift 2
if [[ "$1" == bash && "$2" == -l && "$3" == -c ]]; then exec bash -c "$4"; fi
exec "$@"'
    # A Workbench CLI that starts logged in, as the old account.
    stub wb '
echo "$*" >> "${TEST_ROOT}/wb-calls"
case "$*" in
    "auth revoke") touch "${TEST_ROOT}/logged-out" ;;
    "auth login"*) rm -f "${TEST_ROOT}/logged-out" ;;
    "auth status"*) [[ -f "${TEST_ROOT}/logged-out" ]] && echo "NO USER LOGGED IN" || echo "User email: old" ;;
esac'
    stub gcsfuse 'true'
    export PATH="${TEST_ROOT}/bin:${PATH}"
    export WORKBENCH_INSTALL_PATH="${TEST_ROOT}/bin/wb"
    export USER_NAME="$(id -un)" WORK_DIRECTORY="${HOME_DIR}" \
        USER_WORKBENCH_CONFIG_DIR="${HOME_DIR}/.workbench" CLOUD=gcp
    seed_home
}

stub() {
    printf '#!/bin/bash\nset -euo pipefail\n%s\n' "$2" > "${TEST_ROOT}/bin/$1"
    chmod +x "${TEST_ROOT}/bin/$1"
}

# The owner's cached credentials, and files that must survive a change.
seed_home() {
    mkdir -p "${HOME_DIR}/.ssh" "${HOME_DIR}/.config/git" "${HOME_DIR}/.cache/git/credential" \
        "${HOME_DIR}/.config/gcloud/configurations" "${HOME_DIR}/.config/gcloud/legacy_credentials/owner@example.com" \
        "${HOME_DIR}/repos/analysis"
    for f in .ssh/id_rsa .ssh/id_rsa.pub .ssh/id_ed25519 .git-credentials .config/git/credentials \
        .cache/git/credential/socket .config/gcloud/credentials.db .config/gcloud/access_tokens.db \
        .config/gcloud/application_default_credentials.json \
        .config/gcloud/legacy_credentials/owner@example.com/adc.json; do
        echo secret > "${HOME_DIR}/${f}"
    done
    echo github.com > "${HOME_DIR}/.ssh/known_hosts"
    echo "Host *" > "${HOME_DIR}/.ssh/config"
    echo notebook > "${HOME_DIR}/repos/analysis/README.md"
    printf '[core]\naccount = owner@example.com\nproject = ws-project\n[compute]\nregion = us-central1\n' \
        > "${HOME_DIR}/.config/gcloud/configurations/config_default"
    SEEDED="$(credentials_left)"
}

# Bats ignores a bare "! grep" under errexit.
refute_grep() {
    if grep -q "$@"; then
        return 1
    fi
}

credentials_left() {
    (cd "${HOME_DIR}" && find .ssh/id_* .git-credentials .config/git/credentials .cache/git/credential \
        .config/gcloud/credentials.db .config/gcloud/access_tokens.db .config/gcloud/legacy_credentials \
        .config/gcloud/application_default_credentials.json 2>/dev/null) || true
}

assert_cleared() {
    [ -z "$(credentials_left)" ]
    refute_grep '^account' "${HOME_DIR}/.config/gcloud/configurations/config_default"
    grep -q '^project = ws-project$' "${HOME_DIR}/.config/gcloud/configurations/config_default"
    grep -q '^region = us-central1$' "${HOME_DIR}/.config/gcloud/configurations/config_default"
    [ -f "${HOME_DIR}/.ssh/known_hosts" ] && [ -f "${HOME_DIR}/.ssh/config" ]
    [ -f "${HOME_DIR}/repos/analysis/README.md" ]
}

assert_untouched() {
    [ "$(credentials_left)" = "${SEEDED}" ]
    grep -q '^account = owner@example.com$' "${HOME_DIR}/.config/gcloud/configurations/config_default"
}

vm_account() {
    printf '%s' "$1" > "${TEST_ROOT}/email"
}

recorded() {
    printf '%s\n' "$1" > "${HOME_DIR}/.workbench/service-account"
}

# Each call stands for a new run of the sourcing script.
check() {
    if declare -F check_service_account > /dev/null; then
        ACCOUNT_CHANGED=false SHARED_APPS_READER=false SERVICE_ACCOUNT_EMAIL=""
    else
        source "${STARTUP}/emit.sh"
        source "${STARTUP}/account-change.sh"
    fi
    check_service_account
}

remount() {
    run bash "${STARTUP}/remount-on-restart.sh" "${USER_NAME}" "${HOME_DIR}" gcp true
}

@test "a change from the owner's account to the reader account clears cached credentials" {
    vm_account "${READER}"
    recorded "${OWNER}"
    check
    [ "${ACCOUNT_CHANGED}" = true ]
    [ "${SHARED_APPS_READER}" = true ]
    assert_cleared
    grep -qx 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email' \
        "${TEST_ROOT}/curl-calls"
    # Recorded only when the caller says so.
    grep -qx "${OWNER}" "${HOME_DIR}/.workbench/service-account"
    record_service_account
    grep -qx "${READER}" "${HOME_DIR}/.workbench/service-account"
}

@test "a change to the writer account clears credentials but keeps read-write mounts" {
    vm_account "${WRITER}"
    recorded "${OWNER}"
    check
    [ "${ACCOUNT_CHANGED}" = true ]
    [ "${SHARED_APPS_READER}" = false ]
    assert_cleared
}

@test "a shared-apps account without a record counts as a change; another account doesn't" {
    vm_account "${READER}"
    check
    [ "${ACCOUNT_CHANGED}" = true ]
    assert_cleared

    seed_home
    vm_account "${OWNER}"
    check
    [ "${ACCOUNT_CHANGED}" = false ]
    assert_untouched
    record_service_account
    grep -qx "${OWNER}" "${HOME_DIR}/.workbench/service-account"
}

@test "an unchanged account, an unreadable one, or AWS leaves credentials alone" {
    vm_account "${READER}"
    recorded "${READER}"
    check
    [ "${ACCOUNT_CHANGED}" = false ]
    [ "${SHARED_APPS_READER}" = true ]
    assert_untouched

    rm "${TEST_ROOT}/email"
    recorded "${OWNER}"
    run check
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"could not read the VM's service account"* ]]
    check 2>/dev/null
    [ "${ACCOUNT_CHANGED}" = false ]
    [ "${SHARED_APPS_READER}" = false ]
    assert_untouched
    record_service_account
    grep -qx "${OWNER}" "${HOME_DIR}/.workbench/service-account"

    vm_account "${READER}"
    : > "${TEST_ROOT}/curl-calls"
    CLOUD=aws check
    [ "${ACCOUNT_CHANGED}" = false ]
    [ ! -s "${TEST_ROOT}/curl-calls" ]
    assert_untouched
}

@test "on restart after a change, the CLI logs out and in, and buckets mount read-only for readers" {
    vm_account "${READER}"
    recorded "${OWNER}"
    remount
    [ "${status}" -eq 0 ]
    assert_cleared
    [ "$(cat "${TEST_ROOT}/wb-calls")" = "auth revoke
auth status
auth login --mode=APP_DEFAULT_CREDENTIALS
resource mount --allow-other --read-only" ]
    grep -qx "${READER}" "${HOME_DIR}/.workbench/service-account"

    # The next restart, with the account unchanged, keeps the login.
    : > "${TEST_ROOT}/wb-calls"
    remount
    [ "${status}" -eq 0 ]
    [ "$(cat "${TEST_ROOT}/wb-calls")" = "auth status
resource mount --allow-other --read-only" ]
}

@test "restarts without a change log in and mount as before" {
    vm_account "${OWNER}"
    recorded "${OWNER}"
    remount
    [ "${status}" -eq 0 ]
    assert_untouched
    [ "$(cat "${TEST_ROOT}/wb-calls")" = "auth status
resource mount --allow-other" ]
}

@test "a failed logout leaves the change unrecorded, so the next restart retries it" {
    vm_account "${WRITER}"
    recorded "${OWNER}"
    stub wb 'echo "$*" >> "${TEST_ROOT}/wb-calls"; [[ "$*" != "auth revoke" ]]'
    remount
    [ "${status}" -ne 0 ]
    grep -qx "${OWNER}" "${HOME_DIR}/.workbench/service-account"
    refute_grep '^resource mount' "${TEST_ROOT}/wb-calls"
}

@test "post-startup's CLI install logs out before logging in after a change" {
    export SCRIPT_DIR="${STARTUP}" CLOUD_SCRIPT_DIR="${STARTUP}/gcp" LOG_IN=true \
        RUN_AS_LOGIN_USER="sudo -u ${USER_NAME} bash -l -c" USER_BASH_COMPLETION_DIR="${TEST_ROOT}/completion"
    mkdir -p "${USER_BASH_COMPLETION_DIR}"
    ACCOUNT_CHANGED=true run bash "${STARTUP}/install-cli.sh"
    [ "${status}" -eq 0 ]
    [ "$(grep '^auth' "${TEST_ROOT}/wb-calls")" = "auth revoke
auth login --mode=APP_DEFAULT_CREDENTIALS" ]

    : > "${TEST_ROOT}/wb-calls"
    ACCOUNT_CHANGED=false run bash "${STARTUP}/install-cli.sh"
    [ "${status}" -eq 0 ]
    [ "$(grep '^auth' "${TEST_ROOT}/wb-calls")" = "auth login --mode=APP_DEFAULT_CREDENTIALS" ]
}

# The VM host: configure-wb.sh with /home/core rewritten into the test directory.
prepare_core() {
    export CORE="${TEST_ROOT}/core"
    mkdir -p "${CORE}/wb"
    sed "s|/home/core|${CORE}|g" "${STARTUP}/butane/030-configure-wb.sh" > "${CORE}/configure-wb.sh"
    sed "s|/home/core|${CORE}|g" "${STARTUP}/butane/gcp/wb-values.sh" > "${CORE}/wb/values.sh"
    cp "${STARTUP}/butane/gcp/metadata-utils.sh" "${CORE}/metadata-utils.sh"
    printf '#!/bin/bash\nexec wb "$@"\n' > "${CORE}/wb.sh"
    chmod +x "${CORE}/wb.sh"
    stub docker 'true'
    stub wb '
echo "$*" >> "${TEST_ROOT}/wb-calls"
case "$*" in
    "auth revoke") touch "${TEST_ROOT}/logged-out" ;;
    "auth login"*) rm -f "${TEST_ROOT}/logged-out" ;;
    "auth status"*) [[ -f "${TEST_ROOT}/logged-out" ]] && echo "{\"loggedIn\":false}" || echo "{\"loggedIn\":true}" ;;
    "server status") echo "Current server: dev-stable" ;;
    "workspace describe"*) echo "{\"id\":\"ws-ufid\"}" ;;
esac'
}

configure_wb() {
    : > "${TEST_ROOT}/wb-calls"
    run bash "${CORE}/configure-wb.sh"
}

host_auth_calls() {
    grep '^auth' "${TEST_ROOT}/wb-calls" || true
}

@test "the host logs the old account out of the Workbench CLI after a change" {
    prepare_core
    vm_account "${READER}"
    printf '%s\n' "${OWNER}" > "${CORE}/service-account"
    configure_wb
    [ "${status}" -eq 0 ]
    [ "$(host_auth_calls)" = "auth revoke
auth status --format json
auth login --mode APP_DEFAULT_CREDENTIALS" ]
    grep -qx "${READER}" "${CORE}/service-account"

    configure_wb
    [ "${status}" -eq 0 ]
    [ "$(host_auth_calls)" = "auth status --format json" ]
}

@test "the host counts a shared-apps account without a record as a change" {
    prepare_core
    vm_account "${WRITER}"
    configure_wb
    [ "${status}" -eq 0 ]
    [ "$(host_auth_calls | head -n 1)" = "auth revoke" ]
    grep -qx "${WRITER}" "${CORE}/service-account"
}

@test "the host keeps the login when the account is unchanged, new, or unreadable" {
    prepare_core
    vm_account "${OWNER}"
    configure_wb
    [ "${status}" -eq 0 ]
    [ "$(host_auth_calls)" = "auth status --format json" ]
    grep -qx "${OWNER}" "${CORE}/service-account"

    rm "${TEST_ROOT}/email"
    configure_wb
    [ "${status}" -eq 0 ]
    [ "$(host_auth_calls)" = "auth status --format json" ]
    grep -qx "${OWNER}" "${CORE}/service-account"
}

@test "the host retries the logout on the next boot if it fails" {
    prepare_core
    vm_account "${WRITER}"
    printf '%s\n' "${OWNER}" > "${CORE}/service-account"
    stub wb 'echo "$*" >> "${TEST_ROOT}/wb-calls"; [[ "$*" != "auth revoke" ]]'
    configure_wb
    [ "${status}" -ne 0 ]
    grep -qx "${OWNER}" "${CORE}/service-account"
}
