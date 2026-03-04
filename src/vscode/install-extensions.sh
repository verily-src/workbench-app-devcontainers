#!/bin/bash
set -e

# Log to file for debugging
LOG_FILE="/config/.workbench/install-extensions-output.txt"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE")
exec 2>&1

echo "=== Extension Installation Started at $(date) ==="

# Wait for code-server to be ready
echo "Waiting for code-server to start..."
TIMEOUT=120
ELAPSED=0
until curl -sf http://localhost:8443 > /dev/null; do
  sleep 1
  ELAPSED=$((ELAPSED + 1))
  if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "ERROR: code-server did not start within ${TIMEOUT} seconds"
    exit 1
  fi
done
echo "Code-server is ready (took ${ELAPSED} seconds)"

# Install extensions as the user
echo "Installing extensions..."
echo "Installing google.geminicodeassist..."
runuser -u abc -- code-server --install-extension google.geminicodeassist || echo "Failed to install google.geminicodeassist"

echo "Installing anthropic.claude-code..."
runuser -u abc -- code-server --install-extension anthropic.claude-code || echo "Failed to install anthropic.claude-code"

echo "Extension installation complete at $(date)"
echo "========================================="
