#!/usr/bin/env bash

# install.sh installs the Gemini CLI in the devcontainer

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

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

apt-get update -y
apt-get install -y --no-install-recommends curl ca-certificates tmux

npm install -g @google/gemini-cli

# Wrap gemini in tmux so its TUI works in browser-based terminals (code-server,
# JupyterLab). No-op if already in a tmux session.
BASHRC="${USER_HOME_DIR}/.bashrc"
if [ -f "${BASHRC}" ] && ! grep -q 'function gemini' "${BASHRC}"; then
    cat >> "${BASHRC}" << 'EOF'
function gemini() {
    if [ -z "$TMUX" ]; then
        tmux kill-session -t "gemini" 2>/dev/null || true
        tmux new-session -d -s "gemini"
        sleep 0.3
        tmux send-keys -t "gemini" "command gemini $(printf '%q ' "$@")" Enter
        tmux attach-session -t "gemini"
    else
        command gemini "$@"
    fi
}
EOF
fi

# Fix NVM ownership so the container user can manage the active-version symlink.
chown -R "${USERNAME}:${USERNAME}" /usr/local/share/nvm 2>/dev/null || true
