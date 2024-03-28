#!/bin/bash

# start-proxy-agent.sh starts the proxy agent on the VM.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <proxyImage>"
    exit 1
fi

readonly PROXY_IMAGE=$1
port=$(docker inspect application-server | jq -r '.[].NetworkSettings.Ports | to_entries[] | .value[] | select(.HostIp == "0.0.0.0" or .HostIp == "::") | .HostPort' | head -n 1)
echo "got port: ${port}"
if [[ -z "${port}" ]]; then
    echo "Error: Port is empty."
    exit 1
else
    echo "port is ${port}"
fi

# shellcheck source=/dev/null
source /home/core/agent.env
docker start "proxy-agent" 2>/dev/null || docker run --name "proxy-agent" --restart=unless-stopped --net=host "${PROXY_IMAGE}" --proxy="${PROXY}" --host="${HOSTNAME}":"${port}" --compute-platform=EC2 --shim-path="${SHIM_PATH}" --rewrite-websocket-host "${REWRITE_WEBSOCKET_HOST}"