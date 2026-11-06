#!/bin/bash

# start-proxy-agent.sh starts the proxy agent on the VM.
# Note: This script requires agent-specific environment to be set in /home/core/agent.env on the VM and
# metadata-utils.sh script to be present in /home/core to get guest attributes for GCE and tag for EC2.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <proxyImage> <GCP/EC2>"
    exit 1
fi

readonly PROXY_IMAGE="$1"
readonly COMPUTE_PLATFORM="$2"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/container-utils.sh"
# This is a required systemd step even when devcontainer up failures are ignored.
# Fail before starting the proxy so incomplete airlock provisioning is retried.
validate_airlock_snapshot
PROXY_CONTAINER=$(find_proxy_container)

#shellcheck source=/dev/null
source /home/core/metadata-utils.sh
SHARE_ENABLED=false
share_status=0
is_share_enabled_vm || share_status=$?
case "${share_status}" in
    0) SHARE_ENABLED=true ;;
    1) ;;
    *)
        # Without the tags, the agent can't tell which address is safe to dial.
        # systemd reruns the unit until they can be read.
        echo "Error: not starting the proxy agent: could not tell whether this VM is share-enabled."
        exit 1
        ;;
esac
readonly SHARE_ENABLED

# A frontend such as the virtual browser isn't the app, so shared ports on it
# wouldn't reach the app.
if [[ "${SHARE_ENABLED}" == true && "${PROXY_CONTAINER}" != application-server ]]; then
    echo "Error: not starting the proxy agent on this share-enabled VM: only apps served by application-server can be shared, not a separate frontend."
    exit 1
fi

# Start an existing frontend without recreating it, before reading its published port.
if [[ "${PROXY_CONTAINER}" != application-server ]]; then
    docker start "${PROXY_CONTAINER}"
fi

if [[ "${SHARE_ENABLED}" == true ]]; then
    # Dial the app container directly on app-network, never the VM's own
    # address, so X-App-Port reaches only the container's ports. This runs on
    # every boot and Docker restart, which picks up a changed address.
    if ! APP_HOST="$(share_enabled_host "${PROXY_CONTAINER}")"; then
        echo "Error: not starting the proxy agent on this share-enabled VM: ${PROXY_CONTAINER} has no valid app-network address and port."
        exit 1
    fi
    echo "Share-enabled VM: the proxy agent forwards to ${APP_HOST} on app-network"
else
    PORT="$(docker inspect "${PROXY_CONTAINER}" \
      | jq -r '.[].NetworkSettings.Ports | to_entries[]? | .value[]? | select(.HostIp == "0.0.0.0" or .HostIp == "::") | .HostPort' \
      | head -n 1)"
    readonly PORT
    if [[ -z "${PORT}" ]]; then
        echo "Error: Proxy target port is empty."
        exit 1
    fi

    echo "Proxy agent port should listen at port ${PORT}"
fi

# shellcheck source=/dev/null
source /home/core/agent.env
if [[ "${SHARE_ENABLED}" != true ]]; then
    APP_HOST="${HOSTNAME}:${PORT}"
fi
readonly APP_HOST
OPTIONS=()
if [[ "${COMPUTE_PLATFORM^^}" == "GCP" ]]; then
    OPTIONS+=("--backend=${BACKEND}")
fi

TERRA_SERVER="$(get_metadata_value "terra-cli-server" "")"
readonly TERRA_SERVER
if [[ "${TERRA_SERVER}" == "dev-stable" ]]; then
    OPTIONS+=("--debug=true")
fi
readonly OPTIONS

# Pull the latest proxy agent. Without internet access, such as an airlocked
# restart, fall back to the local image.
if ! docker pull "${PROXY_IMAGE}"; then
    if ! docker image inspect "${PROXY_IMAGE}" >/dev/null 2>&1; then
        echo "Error: could not pull ${PROXY_IMAGE} and no local image exists."
        exit 1
    fi
    echo "WARNING: could not pull ${PROXY_IMAGE}; using the local image"
fi

# Remove any existing proxy agent container
docker rm -f "proxy-agent" 2>/dev/null || true

docker run \
  --detach \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --name "proxy-agent" \
  --restart=unless-stopped \
  --net=host "${PROXY_IMAGE}" \
  --proxy="${PROXY}" \
  --host="${APP_HOST}" \
  --compute-platform="${COMPUTE_PLATFORM^^}" \
  --shim-path="${SHIM_PATH}" \
  --rewrite-websocket-host="${REWRITE_WEBSOCKET_HOST}" \
  --enable-monitoring-script=true \
  --websocket-transport=true \
  "${OPTIONS[@]}"
