#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly root="${WORKBENCH_ROOT:-}"
readonly lib="${root}/usr/lib/workbench/maintenance"
readonly recognized="${root}/etc/workbench/maintenance/managed-files.sha256"
readonly backup="${root}/var/lib/workbench-maintenance/migration-backup"
readonly mode="${WORKBENCH_MODE:?WORKBENCH_MODE is required}"
readonly cloud="${WORKBENCH_CLOUD:?WORKBENCH_CLOUD is required}"
[[ "${mode}" == runtime || "${mode}" == cache ]]
[[ "${cloud}" == gcp || "${cloud}" == aws ]]

recognized_file() {
    local destination="$1" expected="${2:-}" hash
    [[ -f "${root}${destination}" && ! -L "${root}${destination}" ]] || return 1
    if [[ -n "${expected}" ]] && cmp -s "${root}${destination}" "${root}${expected}"; then
        return 0
    fi
    [[ -f "${recognized}" ]] || return 1
    hash=$(sha256sum "${root}${destination}" | cut -d ' ' -f 1)
    awk -v hash="${hash}" -v path="${destination}" \
        '$1 == hash && substr($0, 67) == path {found=1} END {exit !found}' "${recognized}"
}

backup_file() {
    local path="$1" target="${backup}$1" tmp
    [[ -f "${root}${path}" && ! -L "${root}${path}" ]] || return 0
    if [[ -e "${target}" ]]; then
        [[ ! -L "${target}" ]] && cmp -s "${root}${path}" "${target}"
        return
    fi
    mkdir -p "${backup}"
    chmod 0700 "${backup}"
    mkdir -p "$(dirname "${target}")"
    tmp=$(mktemp "${target}.XXXXXX")
    cp -p "${root}${path}" "${tmp}"
    chmod 0600 "${tmp}"
    mv -f "${tmp}" "${target}"
}

destinations=()
targets=()
while IFS=$'\t' read -r file_mode file_cloud destination target; do
    [[ "${file_mode}" == any || "${file_mode}" == "${mode}" ]] || continue
    [[ "${file_cloud}" == any || "${file_cloud}" == "${cloud}" ]] || continue
    [[ -f "${root}${target}" ]] || { echo "Missing host payload: ${target}" >&2; exit 1; }
    if [[ -L "${root}${destination}" ]]; then
        [[ "$(readlink "${root}${destination}")" == "${root}${target}" ]] || {
            echo "Unrecognized host link: ${destination}" >&2; exit 1;
        }
    elif [[ -e "${root}${destination}" ]] && ! recognized_file "${destination}" "${target}"; then
        echo "Unrecognized host file: ${destination}" >&2
        exit 1
    fi
    destinations+=("${destination}")
    targets+=("${target}")
done < "${lib}/host-files.tsv"

readonly bootstrap=/etc/systemd/system/bootstrap-files.service
if [[ -e "${root}${bootstrap}" || -L "${root}${bootstrap}" ]]; then
    recognized_file "${bootstrap}" || { echo 'Unrecognized legacy bootstrap unit' >&2; exit 1; }
fi

readonly bootstrap_gate=/etc/systemd/system/bootstrap-files.service.d/30-workbench-maintenance.conf
if [[ -e "${root}${bootstrap_gate}" || -L "${root}${bootstrap_gate}" ]]; then
    if [[ -L "${root}${bootstrap_gate}" ]] ||
        ! cmp -s "${root}${bootstrap_gate}" <(printf '[Unit]\nRequires=workbench-maintenance.service\nAfter=workbench-maintenance.service\n'); then
        echo 'Unrecognized legacy bootstrap gate' >&2
        exit 1
    fi
fi

for destination in "${destinations[@]}" "${bootstrap}"; do
    backup_file "${destination}"
done

for ((i=0; i<${#destinations[@]}; i++)); do
    destination="${root}${destinations[$i]}"
    target="${root}${targets[$i]}"
    [[ ! -L "${destination}" ]] || continue
    mkdir -p "$(dirname "${destination}")"
    if [[ -L "${destination}.workbench-tmp" ]]; then
        [[ "$(readlink "${destination}.workbench-tmp")" == "${target}" ]] || exit 1
        rm "${destination}.workbench-tmp"
    fi
    ln -s "${target}" "${destination}.workbench-tmp"
    mv -f "${destination}.workbench-tmp" "${destination}"
done
if [[ -f "${root}${bootstrap}" ]]; then
    systemctl disable bootstrap-files.service
    rm "${root}${bootstrap}"
fi
if [[ -f "${root}${bootstrap_gate}" ]]; then
    rm "${root}${bootstrap_gate}"
fi
