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
PORT="$(docker inspect application-server \
  | jq -r '.[].NetworkSettings.Ports | to_entries[]? | .value[]? | select(.HostIp == "0.0.0.0" or .HostIp == "::") | .HostPort' \
  | head -n 1)"
readonly PORT
if [[ -z "${PORT}" ]]; then
    echo "Error: Application-server port is empty."
    exit 1
fi

echo "Proxy agent port should listen at port ${PORT}"

# shellcheck source=/dev/null
source /home/core/agent.env
OPTIONS=()
if [[ "${COMPUTE_PLATFORM^^}" == "GCP" ]]; then
    OPTIONS+=("--backend=${BACKEND}")
fi

#shellcheck source=/dev/null
source /home/core/metadata-utils.sh
TERRA_SERVER="$(get_metadata_value "terra-cli-server" "")"
readonly TERRA_SERVER
if [[ "${TERRA_SERVER}" == "dev-stable" ]]; then
    OPTIONS+=("--debug=true")
fi
PROXY_WS_TUNNEL="$(get_metadata_value "proxy-websocket-tunnel-enabled" "")"
if [[ "${PROXY_WS_TUNNEL}" == "TRUE" ]]; then
    OPTIONS+=("--websocket-transport=true")
fi
readonly PROXY_WS_TUNNEL
readonly OPTIONS

# Pull the latest proxy agent
docker pull "${PROXY_IMAGE}"

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
  --host="${HOSTNAME}":"${PORT}" \
  --compute-platform="${COMPUTE_PLATFORM^^}" \
  --shim-path="${SHIM_PATH}" \
  --rewrite-websocket-host="${REWRITE_WEBSOCKET_HOST}" \
  --enable-monitoring-script="${ENABLE_MONITORING_SCRIPT:-false}" \
  "${OPTIONS[@]}"
