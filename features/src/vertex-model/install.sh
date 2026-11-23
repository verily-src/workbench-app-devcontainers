#!/usr/bin/env bash

# install.sh installs the vertex-model feature: proxy.py and its start script in /opt/vertex-model.
# They need only the image's python3, curl and jq. See README.md.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly INSTALL_DIR="/opt/vertex-model"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

for tool in python3 curl jq; do
  if ! command -v "${tool}" > /dev/null; then
    apt-get update -y
    DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends python3 curl jq ca-certificates
    rm -rf /var/lib/apt/lists/*
    break
  fi
done

mkdir -p "${INSTALL_DIR}"
install -m 755 "${FEATURE_DIR}/start-server.sh" "${INSTALL_DIR}/start-server.sh"
install -m 644 "${FEATURE_DIR}/proxy.py" "${INSTALL_DIR}/proxy.py"
python3 -m py_compile "${INSTALL_DIR}/proxy.py"
