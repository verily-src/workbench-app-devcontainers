#!/bin/bash

# install-devcontainer-cli.sh installs the devcontainer CLI on the VM.
set -e

echo "install devcontainer cli"
wget -q -O- "https://storage.googleapis.com/devcontainer_cli/cli-0.54.0.tgz" | tar -xz -C /home/core