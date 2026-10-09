#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    MAINTENANCE="${REPO_ROOT}/startupscript/maintenance"
    ACTION="${MAINTENANCE}/actions/link-host-files.sh"
    export WORKBENCH_ROOT="${BATS_TEST_TMPDIR}/root"
    export WORKBENCH_CLOUD=gcp WORKBENCH_MODE=runtime
    export PATH="${BATS_TEST_TMPDIR}/bin:${PATH}"
    mkdir -p "${WORKBENCH_ROOT}/usr/lib/workbench/maintenance" \
        "${WORKBENCH_ROOT}/usr/lib/systemd/system/workbench" "${WORKBENCH_ROOT}/home/core" \
        "${WORKBENCH_ROOT}/etc/workbench/maintenance" "${BATS_TEST_TMPDIR}/bin"
    cp -R "${REPO_ROOT}/startupscript/butane" "${WORKBENCH_ROOT}/usr/lib/workbench/butane"
    cp -R "${MAINTENANCE}/units/"* "${WORKBENCH_ROOT}/usr/lib/systemd/system/workbench/"
    cp "${MAINTENANCE}/host-files.tsv" "${WORKBENCH_ROOT}/usr/lib/workbench/maintenance/"
    printf '#!/bin/bash\nexit 0\n' > "${BATS_TEST_TMPDIR}/bin/systemctl"
    chmod +x "${BATS_TEST_TMPDIR}/bin/systemctl"
}

@test "new runtime hosts link managed payload while preserving app data" {
    mkdir -p "${WORKBENCH_ROOT}/home/core/devcontainer" "${WORKBENCH_ROOT}/var/lib/docker"
    printf checkout > "${WORKBENCH_ROOT}/home/core/devcontainer/app"
    printf state > "${WORKBENCH_ROOT}/home/core/container-state"
    printf image > "${WORKBENCH_ROOT}/var/lib/docker/image"
    "${ACTION}"
    [ -L "${WORKBENCH_ROOT}/home/core/install-node.sh" ]
    [ -L "${WORKBENCH_ROOT}/etc/systemd/system/cleanup.service" ]
    [ -L "${WORKBENCH_ROOT}/etc/fluent-bit.conf" ]
    [ ! -e "${WORKBENCH_ROOT}/home/core/prepare-devcontainer-cache.sh" ]
    [ "$(cat "${WORKBENCH_ROOT}/home/core/devcontainer/app")" = checkout ]
    [ "$(cat "${WORKBENCH_ROOT}/home/core/container-state")" = state ]
    [ "$(cat "${WORKBENCH_ROOT}/var/lib/docker/image")" = image ]
    "${ACTION}"
}

@test "cache AWS mode excludes runtime services and selects AWS helpers" {
    WORKBENCH_CLOUD=aws WORKBENCH_MODE=cache "${ACTION}"
    [ -L "${WORKBENCH_ROOT}/opt/bin/docker-credential-workbench-ecr" ]
    [ -L "${WORKBENCH_ROOT}/home/core/prepare-devcontainer-cache.sh" ]
    [ ! -e "${WORKBENCH_ROOT}/etc/systemd/system/cleanup.service" ]
    [ ! -e "${WORKBENCH_ROOT}/etc/systemd/system/check-for-newer-os-update.service" ]
    [ "$(readlink "${WORKBENCH_ROOT}/etc/systemd/system/devcontainer.service")" = "${WORKBENCH_ROOT}/usr/lib/systemd/system/workbench/cache/devcontainer.service" ]
}

@test "unknown host edits stop migration before any link is changed" {
    printf custom > "${WORKBENCH_ROOT}/home/core/install-node.sh"
    run "${ACTION}"
    [ "${status}" -ne 0 ]
    [ "$(cat "${WORKBENCH_ROOT}/home/core/install-node.sh")" = custom ]
    [ ! -e "${WORKBENCH_ROOT}/home/core/docker-auth.sh" ]
}

@test "known source bytes and private unit hashes can be migrated" {
    cp "${REPO_ROOT}/startupscript/butane/010-install-node.sh" "${WORKBENCH_ROOT}/home/core/install-node.sh"
    mkdir -p "${WORKBENCH_ROOT}/etc/systemd/system"
    printf legacy-unit > "${WORKBENCH_ROOT}/etc/systemd/system/devcontainer.service"
    hash=$(sha256sum "${WORKBENCH_ROOT}/etc/systemd/system/devcontainer.service" | cut -d ' ' -f 1)
    printf '%s  /etc/systemd/system/devcontainer.service\n' "${hash}" > "${WORKBENCH_ROOT}/etc/workbench/maintenance/managed-files.sha256"
    "${ACTION}"
    [ -L "${WORKBENCH_ROOT}/home/core/install-node.sh" ]
    [ -L "${WORKBENCH_ROOT}/etc/systemd/system/devcontainer.service" ]
    [ "$(cat "${WORKBENCH_ROOT}/var/lib/workbench-maintenance/migration-backup/etc/systemd/system/devcontainer.service")" = legacy-unit ]
    cmp "${REPO_ROOT}/startupscript/butane/010-install-node.sh" "${WORKBENCH_ROOT}/var/lib/workbench-maintenance/migration-backup/home/core/install-node.sh"
    "${ACTION}"
}

@test "missing payload and unknown symlink never produce a partial migration" {
    rm "${WORKBENCH_ROOT}/usr/lib/workbench/butane/010-install-node.sh"
    run "${ACTION}"
    [ "${status}" -ne 0 ]
    [ ! -e "${WORKBENCH_ROOT}/home/core/docker-auth.sh" ]
    cp "${REPO_ROOT}/startupscript/butane/010-install-node.sh" "${WORKBENCH_ROOT}/usr/lib/workbench/butane/"
    ln -s /unknown "${WORKBENCH_ROOT}/home/core/install-node.sh"
    run "${ACTION}"
    [ "${status}" -ne 0 ]
    [ "$(readlink "${WORKBENCH_ROOT}/home/core/install-node.sh")" = /unknown ]
}

@test "an interrupted link replacement can be retried" {
    ln -s "${WORKBENCH_ROOT}/usr/lib/workbench/butane/gcp/docker-auth.sh" "${WORKBENCH_ROOT}/home/core/docker-auth.sh.workbench-tmp"
    "${ACTION}"
    [ -L "${WORKBENCH_ROOT}/home/core/docker-auth.sh" ]
    [ ! -e "${WORKBENCH_ROOT}/home/core/docker-auth.sh.workbench-tmp" ]
}

@test "enrollment retires only the checked bootstrap and its generated gate" {
    mkdir -p "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service.d"
    printf legacy-bootstrap > "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service"
    printf '[Unit]\nRequires=workbench-maintenance.service\nAfter=workbench-maintenance.service\n' > "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service.d/30-workbench-maintenance.conf"
    hash=$(sha256sum "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service" | cut -d ' ' -f 1)
    printf '%s  /etc/systemd/system/bootstrap-files.service\n' "${hash}" > "${WORKBENCH_ROOT}/etc/workbench/maintenance/managed-files.sha256"
    "${ACTION}"
    [ ! -e "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service" ]
    [ ! -e "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service.d/30-workbench-maintenance.conf" ]
    [ "$(cat "${WORKBENCH_ROOT}/var/lib/workbench-maintenance/migration-backup/etc/systemd/system/bootstrap-files.service")" = legacy-bootstrap ]
}

@test "an edited bootstrap gate prevents every file replacement" {
    mkdir -p "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service.d"
    printf custom > "${WORKBENCH_ROOT}/etc/systemd/system/bootstrap-files.service.d/30-workbench-maintenance.conf"
    run "${ACTION}"
    [ "${status}" -ne 0 ]
    [ ! -e "${WORKBENCH_ROOT}/home/core/docker-auth.sh" ]
}
