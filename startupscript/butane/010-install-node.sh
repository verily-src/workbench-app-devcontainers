#!/bin/bash

# install-node.sh installs Node.js on the VM. Flatcar linux does not support package manager. So
# instead of installing node.js using package manager, we download the source code and extract it to
# /opt.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Download Node.js from the source code and extract it to /opt
readonly NODE_VERSION="v24.19.0"
readonly NODE_SHA256="f625d97cd707df4ff96254916fbc5ff014f09c09effe5a1e0ca8f6d41a8789d4"

readonly PLATFORM="linux-x64"
readonly NODE_TAR="node-${NODE_VERSION}-${PLATFORM}.tar.gz"
readonly NODE_INSTALL_SRC="https://storage.googleapis.com/bkt-workbench-artifacts/mirror/${NODE_TAR}"
readonly NODE_INSTALL_PATH="/home/core/${NODE_TAR}"

echo "Downloading Node from ${NODE_INSTALL_SRC}" 
wget -q -O "${NODE_INSTALL_PATH}" "${NODE_INSTALL_SRC}"
echo "${NODE_SHA256}  ${NODE_INSTALL_PATH}" | sha256sum -c

echo "Installing Node from ${NODE_INSTALL_PATH}" 
tar -xzf "${NODE_INSTALL_PATH}" -C /opt --strip-components=1
rm -f "${NODE_INSTALL_PATH}"

echo "Installing node packages"
npm --prefix /home/core ci
