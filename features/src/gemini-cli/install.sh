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
apt-get install -y --no-install-recommends curl ca-certificates

npm install -g @google/gemini-cli

# Fix NVM ownership so the container user can manage the active-version symlink.
chown -R "${USERNAME}:${USERNAME}" /usr/local/share/nvm 2>/dev/null || true
