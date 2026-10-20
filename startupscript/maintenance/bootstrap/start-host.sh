#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail
# shellcheck source=boot-common.sh
source "$(dirname "${BASH_SOURCE[0]}")/boot-common.sh"

[[ "${WORKBENCH_CLOUD}" == gcp || "${WORKBENCH_CLOUD}" == aws ]]
[[ "${WORKBENCH_MODE}" == runtime || "${WORKBENCH_MODE}" == cache ]]
assert_runtime_stopped
systemctl daemon-reload
systemctl reset-failed docker.socket
# The NVIDIA extension refresh can leave an active socket with its old listener removed.
timeout --signal=TERM --kill-after=5s 10s systemctl restart docker.socket
units=(containerd.service docker.service devcontainer.service)
if [[ "${WORKBENCH_MODE}" == runtime ]]; then
    units+=(cleanup.service fluentbit.service proxy-prober.timer idle-shutdown.timer
        check-for-newer-os-update.service check-for-newer-os-update.timer machine-stats-exporter.timer)
fi
systemctl --no-block start "${units[@]}"
