#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly WORKBENCH_ROOT="${WORKBENCH_ROOT:-}"
readonly STATE_DIR="${WORKBENCH_ROOT}/var/lib/workbench-maintenance"
readonly LIB_DIR="${WORKBENCH_ROOT}/usr/lib/workbench"
readonly CANONICAL_IMAGE="${WORKBENCH_ROOT}/etc/extensions/workbench.raw"

valid_version() {
    [[ "$1" =~ ^[0-9]{1,16}$ ]]
}

image_version() {
    local name="${1##*/}" version
    version="${name#workbench_}"
    version="${version%_x86-64.raw}"
    valid_version "${version}" && [[ "${name}" == "workbench_${version}_x86-64.raw" ]] || return 1
    printf '%s\n' "${version}"
}

mounted_version() {
    jq -er '.version | select(type == "string" and test("^[0-9]{1,16}$"))' "${LIB_DIR}/release.json"
}

boot_value() {
    [[ -f "${STATE_DIR}/boot.json" ]] || return 0
    jq -er --arg field "$1" '.[$field] // "" | select(type == "string")' "${STATE_DIR}/boot.json"
}

write_boot_state() {
    local active="$1" usable="$2" tmp
    valid_version "${active}"
    [[ -z "${usable}" ]] || valid_version "${usable}"
    tmp=$(mktemp "${STATE_DIR}/boot.json.XXXXXX")
    jq -n --arg active "${active}" --arg usable "${usable}" \
        '{schema:1,active_version:$active,last_usable_version:$usable}' > "${tmp}"
    chmod 0600 "${tmp}"
    mv -f "${tmp}" "${STATE_DIR}/boot.json"
}

link_image() {
    local image="$1" tmp="${CANONICAL_IMAGE}.tmp.$$"
    [[ -f "${image}" ]]
    mkdir -p "$(dirname "${CANONICAL_IMAGE}")"
    ln -s "${image}" "${tmp}"
    mv -f "${tmp}" "${CANONICAL_IMAGE}"
}

assert_runtime_stopped() {
    local unit state
    for unit in containerd.service docker.service; do
        state=$(systemctl show --property=ActiveState --value "${unit}")
        case "${state}" in
            inactive|failed) ;;
            *) echo "Refusing maintenance while ${unit} is ${state}" >&2; return 1 ;;
        esac
    done
}
