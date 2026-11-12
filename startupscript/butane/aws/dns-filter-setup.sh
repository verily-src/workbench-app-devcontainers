#!/bin/bash
# dns-filter-setup.sh configures the boot-time DNS allowlist for airlocked EC2 instances. Runs
# after docker.service starts (see dns-filter-setup.service) and reads the network-policy tag via
# the same Docker-based mechanism every other tag read in this codebase uses. No-ops entirely on
# non-airlocked instances.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh
# shellcheck source=/dev/null
source /home/core/service-utils.sh

# A transient read failure (e.g. a flaky docker pull of the aws-cli image) must fail closed, not
# be treated as "not airlocked" - get_system_tag_checked's exit status tells the two apart.
NETWORK_POLICY=""
READ_OK="false"
for attempt in 1 2 3; do
    if NETWORK_POLICY="$(get_system_tag_checked "network-policy" "")"; then
        READ_OK="true"
        if [[ "${NETWORK_POLICY}" == "DISABLE_ALL" ]]; then
            break
        fi
    fi
    if [[ ${attempt} -lt 3 ]]; then
        sleep 3
    fi
done

if [[ "${READ_OK}" != "true" ]]; then
    echo "Failed to read the network-policy tag after 3 attempts; failing closed." >&2
    exit 1
fi

if [[ "${NETWORK_POLICY}" != "DISABLE_ALL" ]]; then
    echo "Instance is not airlocked (network-policy=${NETWORK_POLICY:-<unset>}); nothing to do."
    exit 0
fi

# Only initializes to open on the genuine first attempt (file doesn't exist yet).
# probe-proxy-readiness.sh marks it restricted once setup succeeds; every boot after that leaves
# it untouched, so the filter starts already restricted.
if [[ ! -f /home/core/dns-filter.env ]]; then
    echo "START_MODE=open" > /home/core/dns-filter.env
fi

DAEMON_JSON="/etc/docker/daemon.json"
# Content-checked rather than gated on a marker file, so this stays correct even if something
# else ever touches daemon.json.
if ! jq -e '.dns == ["172.17.0.1"]' "${DAEMON_JSON}" >/dev/null 2>&1; then
    # Same directory as the target, not /tmp: /tmp can be a different filesystem, which would make
    # the mv below a non-atomic copy instead of a rename.
    DAEMON_JSON_TMP="$(mktemp "${DAEMON_JSON}.XXXXXX")"
    jq '. + {"dns": ["172.17.0.1"]}' "${DAEMON_JSON}" > "${DAEMON_JSON_TMP}"
    # mktemp creates the file 0600; preserve the original's mode rather than silently tightening it.
    chmod --reference="${DAEMON_JSON}" "${DAEMON_JSON_TMP}"
    mv "${DAEMON_JSON_TMP}" "${DAEMON_JSON}"

    # Safe here only because the dns key was just confirmed missing above, which only happens on
    # the genuine first boot - nothing has created a real container yet at this point, the only
    # thing that's run so far is the aws-cli container used by the tag read, already exited.
    systemctl restart docker.service
fi

# Resolves the allowlist template for this instance's region and WSM environment. Every boot,
# since dns-filter.service's bind-mount is static regardless of mode.
IMDS_TOKEN="$(wget --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)"
REGION="$(wget --header "X-aws-ec2-metadata-token: ${IMDS_TOKEN}" -q -O - http://169.254.169.254/latest/meta-data/placement/region)"
WSM_URL="$(get_service_url "wsm" "$(get_metadata_value "terra-cli-server" "prod")")"
WSM_HOST="${WSM_URL#https://}"
WSM_HOST="${WSM_HOST%%/*}"

ALLOWLIST_TMP="$(mktemp /home/core/allowlist.conf.XXXXXX)"
sed "s/\${REGION}/${REGION}/g" /home/core/allowlist.conf.tmpl > "${ALLOWLIST_TMP}"
echo "server=/${WSM_HOST}/169.254.169.253" >> "${ALLOWLIST_TMP}"
chmod 0644 "${ALLOWLIST_TMP}"
mv "${ALLOWLIST_TMP}" /home/core/allowlist.conf

# Blocks direct queries to the real resolver, bypassing the filter. Applied here, not deferred to
# probe-proxy-readiness.sh: Docker can restart already-existing containers (application-server,
# proxy-agent; both have their own restart policy) independently of this boot sequence, before
# that script ever runs. Flushed first since this script re-runs every boot and the rule isn't
# persistent.
nft flush chain ip filter DOCKER-USER
nft insert rule ip filter DOCKER-USER iifname "br-*" ip daddr != 172.17.0.1 udp dport 53 drop
nft insert rule ip filter DOCKER-USER iifname "br-*" ip daddr != 172.17.0.1 tcp dport 53 drop

touch /home/core/airlock-enabled
