#!/bin/bash

# install-devcontainer-cli.sh installs the devcontainer CLI on the VM.
# Download the devcontainer binary from a gcs bucket and extract it to /home/core.
# Workbench hosts the devcontainer binary in gcp project `verily-workbench-public`.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

echo "install devcontainer cli"
wget -q -O- "https://storage.googleapis.com/devcontainer_cli/cli-0.54.0.tgz" \
  | tar -xz -C /home/core
