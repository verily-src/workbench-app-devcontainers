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

readonly WB_MCP_PORT="${PORT:-"9242"}"

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
    echo "Go is not installed. Installing Go 1.25..."
    GOLANG_VERSION="1.25.0"
    case "$(uname -m)" in
        x86_64)  GOLANG_ARCH="amd64" ;;
        aarch64) GOLANG_ARCH="arm64" ;;
        armv7l)  GOLANG_ARCH="armv6l" ;;
        *)       echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
    esac

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
ExecStart=${WB_MCP_BIN} -http -port ${WB_MCP_PORT}
Restart=on-failure
User=${USERNAME}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create a startup script that runs as HTTP daemon
cat > "${WB_MCP_DIR}/start-server.sh" <<EOF
#!/bin/bash
# Start the wb-mcp-server in HTTP mode as a background daemon
# This ensures the server is always available without lazy initialization

WB_MCP_BIN="/opt/wb-mcp-server/wb-mcp-server"
PORT="\${WB_MCP_PORT:-9242}"
LOGFILE="/tmp/wb-mcp-server.log"
RUN_USER="${USERNAME}"

# Check if already running
if pgrep -f "\${WB_MCP_BIN} -http" > /dev/null; then
    echo "wb-mcp-server is already running"
    exit 0
fi

# Start server as the correct user (who has wb auth tokens)
if [ "\$(id -u)" = "0" ] && [ "\${RUN_USER}" != "root" ]; then
    su - "\${RUN_USER}" -c "nohup \${WB_MCP_BIN} -http -port \${PORT} >> \${LOGFILE} 2>&1 &"
else
    nohup "\${WB_MCP_BIN}" -http -port "\${PORT}" >> "\${LOGFILE}" 2>&1 &
fi
echo "Started wb-mcp-server on port \${PORT} as \${RUN_USER}"
echo "Logs: \${LOGFILE}"
EOF

chmod +x "${WB_MCP_DIR}/start-server.sh"

# Create a stop script
cat > "${WB_MCP_DIR}/stop-server.sh" <<'EOF'
#!/bin/bash
# Stop the wb-mcp-server HTTP daemon

WB_MCP_BIN="/opt/wb-mcp-server/wb-mcp-server"

if pgrep -f "${WB_MCP_BIN} -http" > /dev/null; then
    pkill -f "${WB_MCP_BIN} -http"
    echo "Stopped wb-mcp-server"
else
    echo "wb-mcp-server is not running"
fi
EOF

chmod +x "${WB_MCP_DIR}/stop-server.sh"

# Create MCP configuration file for easy client setup (HTTP mode)
cat > "${WB_MCP_DIR}/mcp-config.json" <<EOF
{
  "mcpServers": {
    "wb": {
      "url": "http://127.0.0.1:${WB_MCP_PORT}"
    }
  }
}
EOF

# Make the directory and files accessible to the user
chown -R "${USERNAME}:" "${WB_MCP_DIR}"

# Configure Claude Code MCP server via settings file (works regardless of CLI install order)
CLAUDE_SETTINGS="${USER_HOME_DIR}/.claude.json"
if [[ -f "${CLAUDE_SETTINGS}" ]]; then
    # Merge into existing settings
    jq --arg url "http://127.0.0.1:${WB_MCP_PORT}" \
        '.mcpServers.wb = {"type": "http", "url": $url}' \
        "${CLAUDE_SETTINGS}" > "${CLAUDE_SETTINGS}.tmp" \
        && mv "${CLAUDE_SETTINGS}.tmp" "${CLAUDE_SETTINGS}"
else
    cat > "${CLAUDE_SETTINGS}" <<CLAUDE_EOF
{
  "mcpServers": {
    "wb": {
      "type": "http",
      "url": "http://127.0.0.1:${WB_MCP_PORT}"
    }
  }
}
CLAUDE_EOF
fi
chown "${USERNAME}:" "${CLAUDE_SETTINGS}"
echo "Configured Claude Code MCP server in ${CLAUDE_SETTINGS}"

# Configure Gemini CLI MCP server via settings file
GEMINI_SETTINGS="${USER_HOME_DIR}/.gemini/settings.json"
mkdir -p "${USER_HOME_DIR}/.gemini"
if [[ -f "${GEMINI_SETTINGS}" ]]; then
    jq --arg url "http://127.0.0.1:${WB_MCP_PORT}" \
        '.mcpServers.wb = {"type": "http", "url": $url}' \
        "${GEMINI_SETTINGS}" > "${GEMINI_SETTINGS}.tmp" \
        && mv "${GEMINI_SETTINGS}.tmp" "${GEMINI_SETTINGS}"
else
    cat > "${GEMINI_SETTINGS}" <<GEMINI_EOF
{
  "mcpServers": {
    "wb": {
      "type": "http",
      "url": "http://127.0.0.1:${WB_MCP_PORT}"
    }
  }
}
GEMINI_EOF
fi
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.gemini"
echo "Configured Gemini CLI MCP server in ${GEMINI_SETTINGS}"


# Add auto-start to .bashrc (idempotent)
if ! grep -q "# Workbench MCP Server - auto-start" "${USER_HOME_DIR}/.bashrc" 2>/dev/null; then
    {
        echo ""
        echo "# Workbench MCP Server - auto-start"
        echo "if ! pgrep -f 'wb-mcp-server -http' > /dev/null 2>&1; then"
        echo "    /opt/wb-mcp-server/start-server.sh > /dev/null 2>&1"
        echo "fi"
    } >> "${USER_HOME_DIR}/.bashrc"
fi

chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo ""
echo "wb-mcp-server installed at ${WB_MCP_BIN}"
echo "Port: ${WB_MCP_PORT}"
echo "Auto-starts on shell login"
echo ""

echo "Done!"
