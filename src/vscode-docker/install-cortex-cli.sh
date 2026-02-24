#!/bin/bash

# install-cortex-cli.sh
#
# Installs cortex-cli from the verily1 monorepo if it exists
# This script runs inside the container after the postCreateCommand

set -o errexit
set -o nounset
set -o pipefail

echo "Checking for verily1 monorepo..."

# Check multiple possible locations for verily1 repo
VERILY1_PATH=""
for path in "/workspace/repos/verily1" "/config/repos/verily1" "$HOME/repos/verily1"; do
  if [[ -d "${path}" ]]; then
    VERILY1_PATH="${path}"
    break
  fi
done

if [[ -z "${VERILY1_PATH}" ]]; then
  echo "verily1 repository not found in any of the expected locations:"
  echo "  - /workspace/repos/verily1"
  echo "  - /config/repos/verily1"
  echo "  - \$HOME/repos/verily1"
  echo "Skipping cortex-cli installation"
  exit 0
fi

readonly VERILY1_PATH

echo "Found verily1 repository at ${VERILY1_PATH}"

# Verify Go is installed
if ! command -v go &> /dev/null; then
  echo "Error: Go is not installed or not in PATH"
  exit 1
fi

echo "Go version: $(go version)"

# Set up Go environment if not already set
export GOPATH="${GOPATH:-/config/go}"
export PATH="${PATH}:${GOPATH}/bin"

echo "GOPATH: ${GOPATH}"
echo "Installing cortex-cli..."

# Navigate to verily1 and install cortex-cli
cd "${VERILY1_PATH}"

if [[ ! -d "cortex/tools/cortex-cli" ]]; then
  echo "Error: cortex-cli source not found at cortex/tools/cortex-cli"
  exit 1
fi

# Install cortex-cli as user abc (where SSH keys are configured)
echo "Installing cortex-cli as user abc (root doesn't have SSH keys)..."
if su - abc -c "export GOPATH=${GOPATH} && export PATH=/usr/local/go/bin:\${GOPATH}/bin:\${PATH} && cd ${VERILY1_PATH} && go install ./cortex/tools/cortex-cli"; then
  echo "cortex-cli installed successfully to ${GOPATH}/bin/cortex-cli"

  # Verify installation
  if [[ -f "${GOPATH}/bin/cortex-cli" ]]; then
    echo "Verifying cortex-cli installation..."
    "${GOPATH}/bin/cortex-cli" --help || echo "cortex-cli binary exists but --help failed"
  else
    echo "Warning: cortex-cli binary not found at expected location ${GOPATH}/bin/cortex-cli"
  fi
else
  echo "Error: Failed to install cortex-cli"
  exit 1
fi

echo "cortex-cli installation complete"
