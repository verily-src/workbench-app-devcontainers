#!/usr/bin/env bash
set -eu

# Function to install Gemini CLI
install_gemini_cli() {
    echo "Installing Gemini CLI..."
    npm install -g @google/gemini-cli

    if command -v gemini >/dev/null; then
        echo "Gemini CLI installed successfully!"
        return 0
    else
        echo "ERROR: Gemini CLI installation failed!"
        return 1
    fi
}

# Function to fix permissions for non-root users
fix_permissions() {
    local username="${1:-root}"

    if [ "${username}" = "root" ]; then
        return 0
    fi

    # Fix NVM permissions: node feature installs as root, causing "Permission denied" in non-root containers
    local nvm_dir="${NVM_DIR:-/usr/local/share/nvm}"
    if [ -d "${nvm_dir}" ]; then
        echo "Fixing NVM permissions for user ${username}..."
        chown -R "${username}:" "${nvm_dir}"
    fi

    # Fix npm cache: npm install -g as root creates root-owned files in user's ~/.npm
    local user_home
    user_home=$(eval echo "~${username}" 2>/dev/null || echo "/home/${username}")
    if [ -d "${user_home}/.npm" ]; then
        echo "Fixing npm cache ownership for user ${username}..."
        chown -R "${username}:" "${user_home}/.npm"
    fi

    # Edge case: Disable auto-update to prevent gemini from trying to re-exec
    # itself on first run, which fails on freshly provisioned machines.
    mkdir -p "${user_home}/.gemini"
    printf '{"general.enableAutoUpdate": false}\n' > "${user_home}/.gemini/settings.json"
    chown -R "${username}:" "${user_home}/.gemini"
}

# Print error message about requiring Node.js feature
print_nodejs_requirement() {
    cat <<EOF

ERROR: Node.js and npm are required but not found!
Please add the Node.js feature to your devcontainer.json:

  "features": {
    "ghcr.io/devcontainers/features/node:1": {},
    "./.devcontainer/features/gemini-cli": { "username": "your-user" }
  }

EOF
    exit 1
}

echo "Activating feature 'gemini-cli'"

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
    print_nodejs_requirement
fi

install_gemini_cli || exit 1

fix_permissions "${USERNAME:-root}"

echo "Done!"