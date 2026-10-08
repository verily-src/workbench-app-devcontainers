#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail
# shellcheck source=boot-common.sh
source "$(dirname "${BASH_SOURCE[0]}")/boot-common.sh"

assert_runtime_stopped
readonly version="$(mounted_version)"
[[ "${version}" == "$(boot_value active_version)" ]]
readonly started=${SECONDS}
"${LIB_DIR}/maintenance/run-actions.sh" "${LIB_DIR}/maintenance/actions.json" "${STATE_DIR}"
write_boot_state "${version}" "${version}"
printf 'workbench_maintenance_seconds=%s\n' "$((SECONDS - started))"
