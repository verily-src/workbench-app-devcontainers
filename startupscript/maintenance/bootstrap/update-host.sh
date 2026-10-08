#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail
# shellcheck source=boot-common.sh
source "$(dirname "${BASH_SOURCE[0]}")/boot-common.sh"

readonly SEED_DIR="${WORKBENCH_ROOT}/etc/workbench/maintenance"

merge_trust() {
    local seed="${SEED_DIR}/import-pubring.gpg" admin="${WORKBENCH_ROOT}/etc/systemd/import-pubring.gpg"
    local previous="${WORKBENCH_ROOT}/usr/lib/systemd/import-pubring.gpg" tmp size
    [[ -s "${seed}" ]]
    [[ ! -e "${admin}" ]] || previous="${admin}"
    size=$(wc -c < "${seed}")
    if [[ -f "${previous}" ]] && tail -c "${size}" "${previous}" | cmp -s - "${seed}"; then
        return 0
    fi
    mkdir -p "$(dirname "${admin}")"
    tmp=$(mktemp "${admin}.XXXXXX")
    [[ ! -f "${previous}" ]] || cat "${previous}" > "${tmp}"
    cat "${seed}" >> "${tmp}"
    chmod 0644 "${tmp}"
    mv -f "${tmp}" "${admin}"
    sha256sum "${seed}" | cut -d ' ' -f 1 > "${STATE_DIR}/trust-key.sha256"
}

refresh_image() {
    local image="$1" version
    version=$(image_version "${image}")
    link_image "${image}"
    timeout --signal=TERM --kill-after=5s 15s systemd-sysext refresh &&
        [[ "$(mounted_version)" == "${version}" ]]
}

download_approved_image() {
    local updater="${WORKBENCH_ROOT}/usr/lib/systemd/systemd-sysupdate" newest='' image version metadata
    "${updater}" --component=workbench update >&2
    for image in "${STATE_DIR}/images/"workbench_*_x86-64.raw; do
        [[ -f "${image}" ]] || continue
        version=$(image_version "${image}") || continue
        newest=$(printf '%s\n%s\n' "${newest}" "${version}" | sort -n | tail -n 1)
    done
    [[ -n "${newest}" ]] || return 0
    metadata=$("${updater}" --component=workbench --json=short list "${newest}")
    jq -er --arg version "${newest}" \
        'select(.version == $version and .available and .installed and (.obsolete | not) and (.incomplete | not)) | .version' \
        <<< "${metadata}"
}

if [[ "${1:-}" == --download ]]; then
    download_approved_image
    exit
fi
[[ $# == 0 ]] || exit 2

umask 077
mkdir -p "${STATE_DIR}/images"
exec 9> "${STATE_DIR}/boot.lock"
flock 9
assert_runtime_stopped

readonly channel="${WORKBENCH_CHANNEL:?WORKBENCH_CHANNEL is required}"
[[ "${channel}" =~ ^https://[a-zA-Z0-9./_-]+$ ]] || { echo 'Invalid maintenance channel' >&2; exit 1; }
readonly dropin="${WORKBENCH_ROOT}/run/sysupdate.workbench.d/workbench.transfer.d"
mkdir -p "${dropin}"
old_image=''
if [[ -L "${CANONICAL_IMAGE}" ]]; then
    old_image=$(readlink -f "${CANONICAL_IMAGE}")
    [[ "${old_image%/*}" == "${STATE_DIR}/images" ]]
    image_version "${old_image}" >/dev/null
elif [[ -e "${CANONICAL_IMAGE}" ]]; then
    echo 'Refusing an unmanaged Workbench image' >&2
    exit 1
fi
usable=$(boot_value last_usable_version)
[[ -z "${usable}" ]] || valid_version "${usable}"
{
    printf '[Transfer]\n'
    [[ -z "${old_image}" ]] || printf 'ProtectVersion=%s\n' "$(image_version "${old_image}")"
    [[ -z "${usable}" ]] || printf 'ProtectVersion=%s\n' "${usable}"
    printf '[Source]\nPath=%s/\n' "${channel%/}"
    printf '[Target]\nPath=%s/images\nCurrentSymlink=%s/candidate.raw\n' "${STATE_DIR}" "${STATE_DIR}"
} > "${dropin}/90-boot.conf.tmp"
mv -f "${dropin}/90-boot.conf.tmp" "${dropin}/90-boot.conf"
merge_trust

selected="${old_image}"
started=${SECONDS}
if newest=$(timeout --signal=TERM --kill-after=5s 25s "$0" --download); then
    [[ -z "${newest}" ]] || selected="${STATE_DIR}/images/workbench_${newest}_x86-64.raw"
else
    echo 'Workbench download failed; keeping the installed image' >&2
fi
printf 'workbench_download_seconds=%s\n' "$((SECONDS - started))"

if [[ -z "${selected}" || ! -f "${selected}" ]]; then
    selected="${STATE_DIR}/images/workbench_${usable}_x86-64.raw"
fi
if [[ ! -f "${selected}" ]]; then
    echo 'No installed Workbench image is available' >&2
    exit 1
fi
version=$(image_version "${selected}")
if [[ "${selected}" != "${old_image}" || "$(mounted_version 2>/dev/null || true)" != "${version}" ]]; then
    started=${SECONDS}
    if ! refresh_image "${selected}"; then
        echo 'Workbench activation failed; restoring the installed image' >&2
        restored=false
        previous="${selected}"
        for fallback in "${old_image}" "${STATE_DIR}/images/workbench_${usable}_x86-64.raw"; do
            [[ -f "${fallback}" && "${fallback}" != "${selected}" && "${fallback}" != "${previous}" ]] || continue
            previous="${fallback}"
            if refresh_image "${fallback}"; then
                version=$(image_version "${fallback}")
                restored=true
                break
            fi
        done
        [[ "${restored}" == true ]] || exit 1
    fi
    printf 'workbench_activation_seconds=%s\n' "$((SECONDS - started))"
fi
[[ "$(mounted_version)" == "${version}" ]]
write_boot_state "${version}" "${usable}"
systemctl daemon-reload
assert_runtime_stopped
systemctl --no-block start workbench-maintenance.service
