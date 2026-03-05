#!/bin/sh
set -eu

# Function to detect the package manager and OS type
detect_package_manager() {
    for pm in apt-get apk dnf yum; do
        if command -v $pm >/dev/null; then
            case $pm in
                apt-get) echo "apt" ;;
                *) echo "$pm" ;;
            esac
            return 0
        fi
    done
    echo "unknown"
    return 1
}

# Function to install packages using the appropriate package manager
install_packages() {
    local pkg_manager="$1"
    shift
    local packages="$@"

    case "$pkg_manager" in
        apt)
            apt-get update
            apt-get install -y $packages
            ;;
        apk)
            apk add --no-cache $packages
            ;;
        dnf|yum)
            $pkg_manager install -y $packages
            ;;
        *)
            echo "WARNING: Unsupported package manager. Cannot install packages: $packages"
            return 1
            ;;
    esac

    return 0
}

# Function to install Node.js
install_nodejs() {
    local pkg_manager="$1"

    echo "Installing Node.js using $pkg_manager..."

    case "$pkg_manager" in
        apt)
            install_packages apt "ca-certificates curl gnupg"
            mkdir -p /etc/apt/keyrings
            curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
            echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_18.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list
            apt-get update
            apt-get install -y nodejs
            ;;
        apk)
            install_packages apk "nodejs npm"
            ;;
        dnf)
            install_packages dnf "nodejs npm"
            ;;
        yum)
            curl -sL https://rpm.nodesource.com/setup_18.x | bash -
            yum install -y nodejs
            ;;
        *)
            echo "ERROR: Unsupported package manager for Node.js installation"
            return 1
            ;;
    esac

    if command -v node >/dev/null && command -v npm >/dev/null; then
        echo "Successfully installed Node.js and npm"
        return 0
    else
        echo "Failed to install Node.js and npm"
        return 1
    fi
}

# Function to install Gemini CLI
install_gemini_cli() {
    echo "Installing Gemini CLI..."
    npm install -g @google/gemini-cli

    if command -v gemini >/dev/null; then
        echo "Gemini CLI installed successfully at: $(command -v gemini)"
        return 0
    else
        echo "ERROR: Gemini CLI installation failed!"
        return 1
    fi
}

# Print error message about requiring Node.js feature
print_nodejs_requirement() {
    cat <<EOF

ERROR: Node.js and npm are required but could not be installed!
Please add the Node.js feature to your devcontainer.json:

  "features": {
    "ghcr.io/devcontainers/features/node:1": {},
    "./.devcontainer/features/gemini-cli": {}
  }

EOF
    exit 1
}

# Main script starts here
main() {
    echo "Activating feature 'gemini-cli'"

    # Detect package manager
    PKG_MANAGER=$(detect_package_manager)
    echo "Detected package manager: $PKG_MANAGER"

    # Install tmux (required for TUI support in browser-based terminals)
    install_packages "$PKG_MANAGER" tmux

    # Try to install Node.js if it's not available
    if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
        echo "Node.js or npm not found, attempting to install automatically..."
        install_nodejs "$PKG_MANAGER" || print_nodejs_requirement
    fi

    # Install Gemini CLI
    install_gemini_cli || exit 1

    # Wrap gemini in tmux so its TUI works in browser-based terminals (code-server,
    # JupyterLab). tmux provides the PTY raw-mode support these terminals lack.
    # No-op if already inside a tmux session.
    BASHRC="${HOME}/.bashrc"
    if [ -f "${BASHRC}" ] && ! grep -q 'function gemini' "${BASHRC}"; then
        cat >> "${BASHRC}" << 'EOF'
function gemini() {
    if [ -z "$TMUX" ]; then
        tmux kill-session -t "gemini" 2>/dev/null || true
        tmux new-session -d -s "gemini"
        sleep 0.3
        tmux send-keys -t "gemini" "gemini" Enter
        tmux attach-session -t "gemini"
    else
        command gemini "$@"
    fi
}
EOF
    fi
}

# Execute main function
main
