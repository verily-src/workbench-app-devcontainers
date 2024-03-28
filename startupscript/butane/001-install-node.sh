#!/bin/bash

# install-node.sh installs Node.js on the VM. Flatcar linux does not support package manager. So
# instead of installing node.js using package manager, we download the source code and extract it to
# /opt.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Download Node.js from the source code and extract it to /opt
readonly NODE_INSTALL_SRC="https://nodejs.org/dist/v18.16.1/node-v18.16.1-linux-x64.tar.gz"
readonly NODE_INSTALL_PATH="/home/core/node-v18.16.1-linux-x64.tar.gz"

echo "Downloading Node from ${NODE_INSTALL_SRC}" 
wget -q -O "${NODE_INSTALL_PATH}" "${NODE_INSTALL_SRC}"

echo "Installing Node from ${NODE_INSTALL_PATH}" 
tar -xzf "${NODE_INSTALL_PATH}" -C /opt --strip-components=1
rm -f "${NODE_INSTALL_PATH}"
