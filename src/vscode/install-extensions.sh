#!/bin/bash
set -e

# Wait for code-server to be ready
echo "Waiting for code-server to start..."
until curl -sf http://localhost:8443 > /dev/null; do
  sleep 1
done
echo "Code-server is ready"

# Install extensions as the user
echo "Installing extensions..."
su - abc -c "code-server --install-extension google.geminicodeassist"
su - abc -c "code-server --install-extension anthropic.claude-code"

echo "Extension installation complete"
