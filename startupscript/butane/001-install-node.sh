#!/bin/bash
# install-node.sh installs Node.js on the VM.
set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

wget -q -O /home/core/node-v18.16.1-linux-x64.tar.gz https://nodejs.org/dist/v18.16.1/node-v18.16.1-linux-x64.tar.gz
tar -xzf /home/core/node-v18.16.1-linux-x64.tar.gz -C /opt --strip-components=1
rm -f /home/core/node-v18.16.1-linux-x64.tar.gz
