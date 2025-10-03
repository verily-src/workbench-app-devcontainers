#!/usr/bin/env bash

# install-conda.sh installs conda and mamba into the devcontainer.
# Installation steps taken from https://github.com/rocker-org/devcontainer-features/blob/main/src/miniforge/install.sh
#
# This script is expected to be sourced from install.sh, with USERNAME and
# USER_HOME_DIR variables set. When it completes, conda will be installed for
# the specified user and also added to the current shell.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CONDA_DIR="/opt/conda"

install_miniforge() {
    local conda_dir=$1
    local download_url
    download_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh"

    check_packages curl ca-certificates
    mkdir -p /tmp/miniforge
    (
        cd /tmp/miniforge
        curl -sLo miniforge.sh "${download_url}"
        chmod +x miniforge.sh
        /bin/bash miniforge.sh -b -p "${conda_dir}"
    )
    rm -rf /tmp/miniforge
    "${conda_dir}/bin/conda" clean -yaf
}

check_packages curl ca-certificates

# Ensure that login shells get the correct path if the user updated the PATH using ENV.
rm -f /etc/profile.d/00-restore-env.sh
echo "export PATH=${PATH//$(sh -lc 'echo $PATH')/\$PATH}" >/etc/profile.d/00-restore-env.sh
chmod +x /etc/profile.d/00-restore-env.sh

# Install the miniforge
echo "Downloading Miniforge3..."
install_miniforge "${CONDA_DIR}"

CONDA_SCRIPT="${CONDA_DIR}/etc/profile.d/conda.sh"
# shellcheck source=/dev/null
source "${CONDA_SCRIPT}"
conda config --set env_prompt '({name})'
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.conda" || true
chown "${USERNAME}:" "${USER_HOME_DIR}/.condarc" || true

echo "source ${CONDA_SCRIPT}" >> "${USER_HOME_DIR}/.bashrc"
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

chown -R "${USERNAME}:" "${CONDA_DIR}"
chmod -R g+r+w "${CONDA_DIR}"
find "${CONDA_DIR}" -type d -print0 | xargs -n 1 -0 chmod g+s
