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
echo "GOPATH is set to: ${GOPATH}"

# Create a temporary script to run as abc user
# This ensures we capture all output properly
INSTALL_SCRIPT="/tmp/install-cortex-cli-inner.sh"
cat > "${INSTALL_SCRIPT}" << 'EOF'
#!/bin/bash
set -x  # Show commands being executed
export GOPATH=/config/go
export PATH=/usr/local/go/bin:${GOPATH}/bin:${PATH}
cd /config/repos/verily1
exec go install ./cortex/tools/cortex-cli 2>&1
EOF

chmod +x "${INSTALL_SCRIPT}"

echo "Running go install as user abc..."
echo "Temp script location: ${INSTALL_SCRIPT}"
echo "Temp script contents:"
cat "${INSTALL_SCRIPT}"
echo "---"
echo "Testing if user abc exists:"
id abc || echo "User abc does not exist!"
echo "Testing if bash exists:"
which bash || echo "bash not found!"
echo "Now running the install script..."
set -x
if su abc -c "bash ${INSTALL_SCRIPT}" 2>&1; then
set +x
  echo "cortex-cli installed successfully to ${GOPATH}/bin/cortex-cli"

  # Verify installation
  if [[ -f "${GOPATH}/bin/cortex-cli" ]]; then
    echo "Verifying cortex-cli installation..."
    "${GOPATH}/bin/cortex-cli" --help || echo "cortex-cli binary exists but --help failed"
  else
    echo "Warning: cortex-cli binary not found at expected location ${GOPATH}/bin/cortex-cli"
    echo "Checking if it installed elsewhere..."
    find /config -name "cortex-cli" 2>/dev/null || echo "cortex-cli not found in /config"
  fi

  rm -f "${INSTALL_SCRIPT}"
else
  EXIT_CODE=$?
  echo "Error: Failed to install cortex-cli (exit code: ${EXIT_CODE})"
  echo "Check the output above for errors from go install"
  rm -f "${INSTALL_SCRIPT}"
  exit 1
fi

echo "cortex-cli installation complete"
