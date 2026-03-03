#!/bin/bash
set -e

echo "Installing Gemini Code Assist extension..."

# Try to install as the abc user (code-server user)
su - abc -c 'code-server --install-extension Google.geminicodeassist' || {
    echo "Failed to install as user abc, trying as root..."
    code-server --install-extension Google.geminicodeassist
}

echo "Gemini Code Assist extension installation completed"
