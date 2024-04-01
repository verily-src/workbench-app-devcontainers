#!/bin/bash

# start-proxy-agent.sh starts the proxy agent on the VM.
# Note: This scripts requires agent specific environment to be set in /home/core/agent.env on the VM.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 2 ]]; then
    echo "usage: $0 <proxyImage> <GCE/EC2>"
    exit 1
fi

readonly PROXY_IMAGE="$1"
readonly COMPUTE_PLATFORM="$2"
PORT="$(docker inspect application-server \
  | jq -r '.[].NetworkSettings.Ports | to_entries[] | .value[] | select(.HostIp == "0.0.0.0" or .HostIp == "::") | .HostPort' \
  | head -n 1)"
readonly PORT
if [[ -z "${PORT}" ]]; then
    echo "Error: Application-server port is empty."
    exit 1
fi

echo "Proxy agent port should listen at port ${PORT}"

# shellcheck source=/dev/null
source /home/core/agent.env
options=()
if [[ "${COMPUTE_PLATFORM^^}" == "GCE" ]]; then
    options+=("--backend=${BACKEND}")
fi
docker start "proxy-agent" 2>/dev/null \
  || docker run \
      --name "proxy-agent" \
      --restart=unless-stopped \
      --net=host "${PROXY_IMAGE}" \
      --proxy="${PROXY}" \
      --host="${HOSTNAME}":"${PORT}" \
      --compute-platform="${COMPUTE_PLATFORM^^}" \
      --shim-path="${SHIM_PATH}" \
      --rewrite-websocket-host="${REWRITE_WEBSOCKET_HOST}" \
      "${options[@]}"
