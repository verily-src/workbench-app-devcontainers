#!/usr/bin/env bats

setup() {
    [[ -n "${MAINTENANCE_IMAGE_ROOT:-}" ]] || skip 'requires an assembled maintenance image'
    command -v systemd-analyze >/dev/null || skip 'requires systemd-analyze'
    ROOT="${BATS_TEST_TMPDIR}/root"
    mkdir -p "${ROOT}/etc/systemd/system"
    cp -a "${MAINTENANCE_IMAGE_ROOT}/usr" "${ROOT}/usr"
}

@test "systemd loads both modes through the installed maintenance unit links" {
    local mode target
    for mode in runtime cache; do
        target="${ROOT}/usr/lib/systemd/system/workbench/${mode}/devcontainer.service"
        # Isolate unit loading from dependencies that only exist inside the VM.
        printf '[Unit]\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/bin/true\n' > "${target}"
        ln -sf "${target}" "${ROOT}/etc/systemd/system/devcontainer.service"
        run env SYSTEMD_UNIT_PATH="${ROOT}/etc/systemd/system:${ROOT}/usr/lib/systemd/system" \
            systemd-analyze verify devcontainer.service
        [ "$status" -eq 0 ]
    done
}
