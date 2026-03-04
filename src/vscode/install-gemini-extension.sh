#!/bin/bash
# Script to install Gemini Code Assist extension after code-server is ready
# Runs in background during provisioning to not block other setup

echo "Waiting for code-server to be ready..."

# Wait up to 60 seconds for code-server to be accessible
for i in {1..60}; do
    if su - abc -c 'code-server --list-extensions' &> /dev/null; then
        echo "code-server is ready!"
        break
    fi
    echo "Waiting for code-server... ($i/60)"
    sleep 1
done

# Install Gemini Code Assist extension
echo "Installing Gemini Code Assist extension..."
su - abc -c 'code-server --install-extension Google.geminicodeassist'

if [ $? -eq 0 ]; then
    echo "Gemini Code Assist extension installed successfully!"
else
    echo "WARNING: Failed to install Gemini Code Assist extension"
fi
