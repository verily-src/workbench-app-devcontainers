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

# Tells dns-filter.service which mode to start the filter in (read via EnvironmentFile). Only the
# instance's first boot needs the filter open - setup never needs internet access again on any
# boot after that, so starting already restricted avoids a window where the filter is open while
# the app container (already running again via its own Docker restart policy) is reachable.
if [[ -f /home/core/first-boot ]]; then
    echo "START_MODE=restricted" > /home/core/dns-filter.env
else
    echo "START_MODE=open" > /home/core/dns-filter.env
fi

# Only touch daemon.json and restart Docker on the genuine first boot. On every boot after that,
# daemon.json already has the dns key from this block's earlier run, so docker.service's own
# normal startup already has the correct default from the moment it starts - no restart needed,
# and nothing is ever restarted with the old config in place.
if [[ ! -f /home/core/airlock-enabled ]]; then
    DAEMON_JSON="/etc/docker/daemon.json"
    # In the same directory as the target, not the default /tmp: /tmp can be a different
    # filesystem, which would make the mv below a non-atomic copy instead of a rename.
    DAEMON_JSON_TMP="$(mktemp "${DAEMON_JSON}.XXXXXX")"

    # daemon.json is already written by Ignition (log-driver/log-opts) before this script ever
    # runs. Add the dns key without disturbing the rest of the file.
    jq '. + {"dns": ["172.17.0.1"]}' "${DAEMON_JSON}" > "${DAEMON_JSON_TMP}"
    # mktemp creates the file 0600; preserve the original's mode rather than silently tightening it.
    chmod --reference="${DAEMON_JSON}" "${DAEMON_JSON_TMP}"
    mv "${DAEMON_JSON_TMP}" "${DAEMON_JSON}"

    # Safe only because this only ever runs on the genuine first boot (gated above) - nothing has
    # created a real container yet at this point, the only thing that has run so far is the
    # aws-cli container used by get_system_tag above, which has already exited. dns-filter.service
    # (After=dns-filter-setup.service) starts once this restart completes, so the filter and every
    # container after it picks up the new default.
    systemctl restart docker.service
fi

# Block direct queries to the real resolver, bypassing the filter - added here, immediately after
# Docker restarts, not deferred to probe-proxy-readiness.sh: Docker can restart already-existing
# containers (application-server, proxy-agent; both run with their own restart policy) on its own,
# independently of this boot sequence, before that script ever runs.
# Flushed first: this script re-runs every boot and the rule isn't persistent, so without the
# flush, a long-lived, frequently-rebooted instance would accumulate duplicate copies of it.
nft flush chain ip filter DOCKER-USER
nft insert rule ip filter DOCKER-USER iifname "br-*" ip daddr != 172.17.0.1 udp dport 53 drop
nft insert rule ip filter DOCKER-USER iifname "br-*" ip daddr != 172.17.0.1 tcp dport 53 drop

touch /home/core/airlock-enabled
