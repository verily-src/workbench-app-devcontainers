#!/usr/bin/env bash

# install.sh installs the Workbench MCP server in the devcontainer.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-"/home/${USERNAME}"}"
if [[ "${USER_HOME_DIR}" == "/home/root" ]]; then
    USER_HOME_DIR="/root"
fi
readonly USER_HOME_DIR

readonly PORT="${PORT:-"3000"}"

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

WORKDIR="$(mktemp -d)"
readonly WORKDIR

readonly WB_MCP_DIR="/opt/wb-mcp-server"
readonly WB_MCP_BIN="${WB_MCP_DIR}/wb-mcp-server"

function cleanup() {
    rm -rf "${WORKDIR:?}"
    rm -rf /var/lib/apt/lists/*
}

trap 'cleanup' EXIT

function apt_get_update() {
    if [ "$(find /var/lib/apt/lists/* | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update -y
    fi
}

# Checks if packages are installed and installs them if not
function check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update
        apt-get -y install --no-install-recommends "$@"
    fi
}

echo "Starting wb-mcp-server installation..."

# Save the directory where the feature files are located
FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# Install required packages
check_packages \
    ca-certificates \
    curl \
    git

# Check if Go is installed
if ! command -v go &> /dev/null; then
    echo "Go is not installed. Installing Go 1.21..."
    GOLANG_VERSION="1.21.6"
    GOLANG_ARCH="amd64"

    cd "${WORKDIR}"
    curl -fsSL "https://go.dev/dl/go${GOLANG_VERSION}.linux-${GOLANG_ARCH}.tar.gz" -o go.tar.gz
    tar -C /usr/local -xzf go.tar.gz
    export PATH="/usr/local/go/bin:${PATH}"
fi

# Create installation directory
mkdir -p "${WB_MCP_DIR}"

# Copy source files to temporary build directory
BUILD_DIR="${WORKDIR}/wb-mcp-server"
mkdir -p "${BUILD_DIR}"
cp "${FEATURE_DIR}/main.go" "${BUILD_DIR}/"
cp "${FEATURE_DIR}/go.mod" "${BUILD_DIR}/"

# Build the Go binary
cd "${BUILD_DIR}"
go build -o "${WB_MCP_BIN}" main.go

# Make it executable
chmod +x "${WB_MCP_BIN}"

# Create systemd service file for optional automatic startup
cat > "${WB_MCP_DIR}/wb-mcp-server.service" <<EOF
[Unit]
Description=Workbench MCP Server
After=network.target

[Service]
Type=simple
ExecStart=${WB_MCP_BIN}
Restart=on-failure
User=${USERNAME}
StandardInput=socket
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create a helper script to run the server
cat > "${WB_MCP_DIR}/start-server.sh" <<'EOF'
#!/bin/bash
# Helper script to start the wb-mcp-server
exec /opt/wb-mcp-server/wb-mcp-server
EOF

chmod +x "${WB_MCP_DIR}/start-server.sh"

# Create MCP configuration file for easy client setup
cat > "${WB_MCP_DIR}/mcp-config.json" <<EOF
{
  "mcpServers": {
    "wb": {
      "command": "${WB_MCP_BIN}",
      "args": []
    }
  }
}
EOF

# Make the directory and files accessible to the user
chown -R "${USERNAME}:" "${WB_MCP_DIR}"

# Auto-configure Claude CLI if available
if command -v claude &> /dev/null; then
    echo "Found Claude CLI, attempting to add MCP server..."
    su - "${USERNAME}" -c "claude mcp add --transport stdio wb -- ${WB_MCP_BIN}" 2>/dev/null || true
fi

# Auto-configure Gemini CLI if available
if command -v gemini &> /dev/null; then
    echo "Found Gemini CLI, attempting to add MCP server..."
    su - "${USERNAME}" -c "gemini mcp add --scope user wb ${WB_MCP_BIN}" 2>/dev/null || true
fi

# Add environment variables and PATH to .bashrc
{
    echo ""
    echo "# Workbench MCP Server"
    echo "export WB_MCP_SERVER_BIN=\"${WB_MCP_BIN}\""
    echo "export WB_MCP_CONFIG=\"${WB_MCP_DIR}/mcp-config.json\""
} >> "${USER_HOME_DIR}/.bashrc"

# Make sure the login user is the owner of their .bashrc
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo ""
echo "=========================================="
echo "wb-mcp-server installation complete!"
echo "=========================================="
echo ""
echo "The MCP server binary is installed at: ${WB_MCP_BIN}"
echo "Configuration file: ${WB_MCP_DIR}/mcp-config.json"
echo ""
echo "To use with Claude CLI, add this to your Claude config:"
echo "  \"wb\": {"
echo "    \"command\": \"${WB_MCP_BIN}\""
echo "  }"
echo ""
echo "To start the server manually: ${WB_MCP_DIR}/start-server.sh"
echo "=========================================="
echo ""

echo "Done!"
