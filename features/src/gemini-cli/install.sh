#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Function to install Gemini CLI
install_gemini_cli() {
    local username="${1:-root}"
    echo "Installing Gemini CLI..."

    if [ "${username}" = "root" ]; then
        npm install -g @google/gemini-cli@0.34.0
    else
        # Chown the NVM dir and npm cache to the target user so npm install -g
        # can write to them. Both may be root-owned from earlier features in the
        # build pipeline (e.g. claude-code) running npm as root.
        local nvm_dir="${NVM_DIR:-/usr/local/share/nvm}"
        local user_home
        user_home=$(eval echo "~${username}" 2>/dev/null || echo "/home/${username}")
        [ -d "${nvm_dir}" ] && chown -R "${username}:" "${nvm_dir}"
        [ -d "${user_home}/.npm" ] && chown -R "${username}:" "${user_home}/.npm"
        sudo -u "${username}" env PATH="${PATH}" npm install -g @google/gemini-cli@0.34.0
    fi

    # 'command' is a shell builtin and can't be used via env; use 'which' instead.
    if which gemini >/dev/null 2>&1; then
        echo "Gemini CLI installed successfully!"
        return 0
    else
        echo "ERROR: Gemini CLI installation failed!"
        return 1
    fi
}

# Function to configure settings for non-root users
fix_permissions() {
    local username="${1:-root}"

    if [ "${username}" = "root" ]; then
        return 0
    fi

    local user_home
    user_home=$(eval echo "~${username}" 2>/dev/null || echo "/home/${username}")

    # Disable auto-update to prevent gemini from trying to re-exec itself on
    # first run, which fails on freshly provisioned machines.
    # Use ANSI Light theme so colors adapt to both light and dark terminals.
    mkdir -p "${user_home}/.gemini"
    printf '{"general.enableAutoUpdate": false, "ui": {"autoThemeSwitching": false, "theme": "ANSI Light"}}\n' > "${user_home}/.gemini/settings.json"
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

install_gemini_cli "${USERNAME:-root}" || exit 1

fix_permissions "${USERNAME:-root}"

echo "Done!"