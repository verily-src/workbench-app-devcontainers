#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

install_gemini_cli() {
    local username="${1:-root}"
    echo "Installing Gemini CLI..."

    if [ "${username}" = "root" ]; then
        npm install -g @google/gemini-cli@0.34.0
    else
        local nvm_dir="${NVM_DIR:-/usr/local/share/nvm}"
        local user_home
        user_home=$(eval echo "~${username}" 2>/dev/null || echo "/home/${username}")
        [ -d "${nvm_dir}" ] && chown -R "${username}:" "${nvm_dir}"
        [ -d "${user_home}/.npm" ] && chown -R "${username}:" "${user_home}/.npm"
        sudo -u "${username}" env PATH="${PATH}" npm install -g @google/gemini-cli@0.34.0
    fi

    if which gemini >/dev/null 2>&1; then
        echo "Gemini CLI installed successfully!"
        return 0
    else
        echo "ERROR: Gemini CLI installation failed!"
        return 1
    fi
}

fix_permissions() {
    local username="${1:-root}"

    if [ "${username}" = "root" ]; then
        return 0
    fi

    local user_home
    user_home=$(eval echo "~${username}" 2>/dev/null || echo "/home/${username}")

    mkdir -p "${user_home}/.gemini"
    printf '{"general.enableAutoUpdate": false, "ui": {"autoThemeSwitching": false, "theme": "ANSI Light"}}\n' > "${user_home}/.gemini/settings.json"
    chown -R "${username}:" "${user_home}/.gemini"
}

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