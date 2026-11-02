#!/bin/bash
# dns-filter-setup.sh configures the boot-time DNS allowlist for airlocked EC2 instances.
# Runs after docker.service starts (see dns-filter-setup.service) and reads the network-policy
# tag using the same Docker-based mechanism every other tag read in this codebase uses - safe
# here since Docker is already running by the time this script starts.
#
# No-ops entirely on non-airlocked instances: no daemon.json edit, no restart, no flag file.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

# A transient failure to read the tag (e.g. a flaky docker pull of the aws-cli image) is
# indistinguishable from "not airlocked" by this point - get_system_tag returns the same empty
# default either way. Retry a few times before concluding this instance isn't airlocked, since
# that conclusion silently skips the whole rest of this script.
NETWORK_POLICY=""
for attempt in 1 2 3; do
    NETWORK_POLICY="$(get_system_tag "network-policy" "")"
    if [[ "${NETWORK_POLICY}" == "DISABLE_ALL" ]]; then
        break
    fi
    if [[ ${attempt} -lt 3 ]]; then
        sleep 3
    fi
done

if [[ "${NETWORK_POLICY}" != "DISABLE_ALL" ]]; then
    echo "Instance is not airlocked (network-policy=${NETWORK_POLICY:-<unset>}); nothing to do."
    exit 0
fi

DAEMON_JSON="/etc/docker/daemon.json"
# In the same directory as the target, not the default /tmp: /tmp can be a different filesystem,
# which would make the mv below a non-atomic copy instead of a rename.
DAEMON_JSON_TMP="$(mktemp "${DAEMON_JSON}.XXXXXX")"

# daemon.json is already written by Ignition (log-driver/log-opts) before this script ever runs.
# Add the dns key without disturbing the rest of the file.
jq '. + {"dns": ["172.17.0.1"]}' "${DAEMON_JSON}" > "${DAEMON_JSON_TMP}"
# mktemp creates the file 0600; preserve the original's mode rather than silently tightening it.
chmod --reference="${DAEMON_JSON}" "${DAEMON_JSON_TMP}"
mv "${DAEMON_JSON_TMP}" "${DAEMON_JSON}"

# Safe only because nothing has created a real container yet at this point in boot - the only
# thing that has run so far is the aws-cli container used by get_system_tag above, which has
# already exited. dns-filter.service (After=dns-filter-setup.service) starts once this restart
# completes, so the filter and every container after it picks up the new default.
systemctl restart docker.service

touch /home/core/airlock-enabled
