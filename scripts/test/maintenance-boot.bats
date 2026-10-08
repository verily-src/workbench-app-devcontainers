#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    BOOTSTRAP="${REPO_ROOT}/startupscript/maintenance/bootstrap"
    export WORKBENCH_ROOT="${BATS_TEST_TMPDIR}/root"
    export WORKBENCH_CHANNEL=https://artifacts.example/workbench/dev
    export WORKBENCH_CLOUD=gcp WORKBENCH_MODE=runtime
    export CALLS="${BATS_TEST_TMPDIR}/calls"
    export PATH="${BATS_TEST_TMPDIR}/bin:${PATH}"
    STATE="${WORKBENCH_ROOT}/var/lib/workbench-maintenance"
    mkdir -p "${BATS_TEST_TMPDIR}/bin" "${STATE}/images" \
        "${WORKBENCH_ROOT}/usr/lib/systemd" "${WORKBENCH_ROOT}/usr/lib/workbench/maintenance" \
        "${WORKBENCH_ROOT}/etc/workbench/maintenance" "${WORKBENCH_ROOT}/etc/extensions"
    printf vendor > "${WORKBENCH_ROOT}/usr/lib/systemd/import-pubring.gpg"
    printf public-key > "${WORKBENCH_ROOT}/etc/workbench/maintenance/import-pubring.gpg"
    cat > "${BATS_TEST_TMPDIR}/bin/systemctl" <<'SH'
#!/bin/bash
printf 'systemctl %s\n' "$*" >> "${CALLS}"
if [[ "$1" == show ]]; then
    printf '%s\n' "${RUNTIME_STATE:-inactive}"
fi
SH
    cat > "${BATS_TEST_TMPDIR}/bin/timeout" <<'SH'
#!/bin/bash
printf 'timeout %s\n' "$*" >> "${CALLS}"
shift 3
exec "$@"
SH
    cat > "${BATS_TEST_TMPDIR}/bin/flock" <<'SH'
#!/bin/bash
exit 0
SH
    cat > "${WORKBENCH_ROOT}/usr/lib/systemd/systemd-sysupdate" <<'SH'
#!/bin/bash
printf 'sysupdate %s\n' "$*" >> "${CALLS}"
[[ "${DOWNLOAD_EXIT:-0}" == 0 ]] || exit "${DOWNLOAD_EXIT}"
if [[ -n "${DOWNLOAD_VERSION:-}" ]]; then
    printf image > "${WORKBENCH_ROOT}/var/lib/workbench-maintenance/images/workbench_${DOWNLOAD_VERSION}_x86-64.raw"
fi
SH
    cat > "${BATS_TEST_TMPDIR}/bin/systemd-sysext" <<'SH'
#!/bin/bash
printf 'sysext %s\n' "$*" >> "${CALLS}"
image=$(readlink "${WORKBENCH_ROOT}/etc/extensions/workbench.raw")
version=${image##*/workbench_}
version=${version%_x86-64.raw}
[[ "${version}" != "${BAD_VERSION:-}" ]] || exit 1
[[ "${version}" != "${IGNORED_VERSION:-}" ]] || exit 0
jq -n --arg version "${version}" '{version:$version}' > "${WORKBENCH_ROOT}/usr/lib/workbench/release.json"
SH
    chmod +x "${BATS_TEST_TMPDIR}/bin/"* "${WORKBENCH_ROOT}/usr/lib/systemd/systemd-sysupdate"
}

install_cached() {
    local version="$1"
    printf image > "${STATE}/images/workbench_${version}_x86-64.raw"
    ln -s "${STATE}/images/workbench_${version}_x86-64.raw" "${WORKBENCH_ROOT}/etc/extensions/workbench.raw"
    jq -n --arg version "${version}" '{version:$version}' > "${WORKBENCH_ROOT}/usr/lib/workbench/release.json"
    jq -n --arg version "${version}" '{schema:1,active_version:$version,last_usable_version:$version}' > "${STATE}/boot.json"
}

@test "first activation downloads once and queues only maintenance" {
    DOWNLOAD_VERSION=1 run "${BOOTSTRAP}/update-host.sh"
    [ "${status}" = 0 ]
    jq -e '.active_version == "1" and .last_usable_version == ""' "${STATE}/boot.json"
    grep -q 'timeout --signal=TERM --kill-after=5s 25s .*systemd-sysupdate --component=workbench update' "${CALLS}"
    grep -q 'systemctl --no-block start workbench-maintenance.service' "${CALLS}"
    ! grep -q 'start .*docker.service' "${CALLS}"
    [ "$(cat "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg")" = vendorpublic-key ]
}

@test "a skipped release activates the newest image without running app code" {
    install_cached 1
    DOWNLOAD_VERSION=3 run "${BOOTSTRAP}/update-host.sh"
    [ "${status}" = 0 ]
    jq -e '.active_version == "3" and .last_usable_version == "1"' "${STATE}/boot.json"
    [ "$(readlink "${WORKBENCH_ROOT}/etc/extensions/workbench.raw")" = "${STATE}/images/workbench_3_x86-64.raw" ]
    ! grep -q 'devcontainer\|docker start' "${CALLS}"
}

@test "timeout and signature failure preserve mounted cached content without refreshing" {
    install_cached 1
    for result in 124 1; do
        : > "${CALLS}"
        DOWNLOAD_EXIT="${result}" run "${BOOTSTRAP}/update-host.sh"
        [ "${status}" = 0 ]
        jq -e '.active_version == "1"' "${STATE}/boot.json"
        ! grep -q '^sysext ' "${CALLS}"
    done
    [ "$(cat "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg")" = vendorpublic-key ]
}

@test "a failed first download holds maintenance and preserves vendor trust" {
    DOWNLOAD_EXIT=124 run "${BOOTSTRAP}/update-host.sh"
    [ "${status}" -ne 0 ]
    ! grep -q 'start workbench-maintenance.service' "${CALLS}"
    [ "$(cat "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg")" = vendorpublic-key ]
}

@test "failed and silently ignored activations restore the old mounted image" {
    install_cached 1
    for kind in BAD_VERSION IGNORED_VERSION; do
        env "${kind}=3" DOWNLOAD_VERSION=3 "${BOOTSTRAP}/update-host.sh"
        [ "$(readlink "${WORKBENCH_ROOT}/etc/extensions/workbench.raw")" -ef "${STATE}/images/workbench_1_x86-64.raw" ]
        jq -e '.active_version == "1" and .last_usable_version == "1"' "${STATE}/boot.json"
    done
}

@test "a changed admin keyring is retained and gets the maintenance public key once" {
    install_cached 1
    mkdir -p "${WORKBENCH_ROOT}/etc/systemd"
    printf administrator > "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg"
    "${BOOTSTRAP}/update-host.sh"
    "${BOOTSTRAP}/update-host.sh"
    [ "$(cat "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg")" = administratorpublic-key ]
    printf replacement > "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg"
    "${BOOTSTRAP}/update-host.sh"
    [ "$(cat "${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg")" = replacementpublic-key ]
}

@test "active runtime prevents download or activation" {
    RUNTIME_STATE=active run "${BOOTSTRAP}/update-host.sh"
    [ "${status}" -ne 0 ]
    ! grep -q '^sysupdate\|^sysext' "${CALLS}"
}

@test "required action failure retains the last usable version" {
    install_cached 1
    jq '.active_version = "3"' "${STATE}/boot.json" > "${STATE}/next.json"
    mv "${STATE}/next.json" "${STATE}/boot.json"
    printf '{"version":"3"}\n' > "${WORKBENCH_ROOT}/usr/lib/workbench/release.json"
    cat > "${WORKBENCH_ROOT}/usr/lib/workbench/maintenance/run-actions.sh" <<'SH'
#!/bin/bash
exit "${ACTION_EXIT:-0}"
SH
    chmod +x "${WORKBENCH_ROOT}/usr/lib/workbench/maintenance/run-actions.sh"
    ACTION_EXIT=1 run "${BOOTSTRAP}/run-maintenance.sh"
    [ "${status}" -ne 0 ]
    jq -e '.active_version == "3" and .last_usable_version == "1"' "${STATE}/boot.json"
    "${BOOTSTRAP}/run-maintenance.sh"
    jq -e '.last_usable_version == "3"' "${STATE}/boot.json"
}

@test "post-maintenance repairs the socket before queueing mode-specific services" {
    "${BOOTSTRAP}/start-host.sh"
    grep -q '^timeout --signal=TERM --kill-after=5s 10s systemctl restart docker.socket$' "${CALLS}"
    grep -q 'start .*cleanup.service.*machine-stats-exporter.timer' "${CALLS}"
    [ "$(tail -n 1 "${CALLS}")" = 'systemctl --no-block start containerd.service docker.service devcontainer.service cleanup.service fluentbit.service proxy-prober.timer idle-shutdown.timer check-for-newer-os-update.service check-for-newer-os-update.timer machine-stats-exporter.timer' ]
    : > "${CALLS}"
    WORKBENCH_MODE=cache "${BOOTSTRAP}/start-host.sh"
    [ "$(tail -n 1 "${CALLS}")" = 'systemctl --no-block start containerd.service docker.service devcontainer.service' ]
}
