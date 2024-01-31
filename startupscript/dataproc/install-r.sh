#!/bin/bash

# install-r.sh
# Installs the latest version of R
#
# This script is intended to be executed as a Dataproc cluster initialization
# action so such that R is installed and configured on all cluster nodes during
# creation and autoscaling.
# For more information on Initialization actions, see:
# https://cloud.google.com/dataproc/docs/concepts/configuring-clusters/init-actions

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Emit a message with a timestamp
function emit() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

# Define directories and system files
readonly LOGIN_USER="dataproc"
readonly USER_HOME_DIR="/home/${LOGIN_USER}"
readonly USER_WORKBENCH_CONFIG_DIR="${USER_HOME_DIR}/.workbench"
readonly USER_BASHRC="${USER_HOME_DIR}/.bashrc"
readonly R_BIN_DIR='/usr/lib/R/bin'
readonly OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/install-r-output.txt"

# Send stdout and stderr from this script to a file for debugging.
exec >>"${OUTPUT_FILE}"
exec 2>&1

emit "Installing R ..."
# Add CRAN R archive network repository
add-apt-repository "deb https://cloud.r-project.org/bin/linux/debian $(lsb_release -cs)-cran40/"

# Fetch and export the repository's gpg key
# See debian package installation instructions:
# https://cran.r-project.org/bin/linux/debian/
gpg --keyserver keyserver.ubuntu.com \
  --recv-key '95C0FAF38DB3CCAD0C080A7BDC78B2DDEABC47B7'
gpg --armor --export '95C0FAF38DB3CCAD0C080A7BDC78B2DDEABC47B7' |
  sudo tee /etc/apt/trusted.gpg.d/cran_debian_key.asc

# Install r-base package
apt-get update -y
apt-get install r-base -y

# Add R to the PATH in user's bashrc
cat <<EOF >>"${USER_BASHRC}"
# Prepend "${R_BIN_DIR}" (if not already in the path)
if [[ ":\${PATH}:" != *":${R_BIN_DIR}:"* ]]; then
  export PATH="${R_BIN_DIR}":"\${PATH}"
fi
EOF
