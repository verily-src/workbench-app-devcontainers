#!/bin/bash

# install-r.sh
# Installs the latest version of R
#
# This script is intended to be executed as a Dataproc cluster initialization
# action so such that R is installed and configured on all cluster nodes during
# creation and autoscaling.
#
# This action depends on some user home directory directories being created.
# Depending on the cluster node type, these directories may not exist. The workbench
# startup script

# For more information on Initialization actions, see:
# https://cloud.google.com/dataproc/docs/concepts/configuring-clusters/init-actions

# Configure shell
set -o errexit  # Exit on error
set -o nounset  # Treat unset variables as error
set -o pipefail # Surface errors inside pipelines
set -o xtrace   # Output commands before executing them

# Utility function to emit a message with a timestamp
function emit() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

# The linux user that JupyterLab will be running as
readonly LOGIN_USER='dataproc'

# Create an alias for cases when we need to run a shell command as the login user.
# Note that we deliberately use "bash -l" instead of "sh" in order to get bash (instead of dash)
# and to pick up changes to the .bashrc.
#
# This is intentionally not a Bash function, as that can suppress error propagation.
# This is intentionally not a Bash alias as they are not supported in shell scripts.
readonly RUN_AS_LOGIN_USER="sudo -u ${LOGIN_USER} bash -l -c"

# Define directories and paths to binaries and system file
readonly USER_HOME_DIR="/home/${LOGIN_USER}"
readonly USER_WORKBENCH_CONFIG_DIR="${USER_HOME_DIR}/.workbench"
readonly USER_BASHRC="${USER_HOME_DIR}/.bashrc"

readonly OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/install-r-output.txt"

readonly CONDA_BIN_DIR='/opt/conda/miniconda3/bin'
readonly R_BIN_DIR='/usr/lib/R/bin'
readonly RUN_R="${R_BIN_DIR}/R"

# Split stdout and stderr in the rest of this script to an output file for debugging.
# But still output to stdout and stderr so users can also debug via the initialization
# action output files in the cluster staging bucket.
exec > >(tee -a "${OUTPUT_FILE}") 2>&1
exec 2>&1

emit "Installing R ..."

# Ensure that the user's workbench configuration directory exists
mkdir -p "${USER_WORKBENCH_CONFIG_DIR}"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_WORKBENCH_CONFIG_DIR}'"

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

# Install IRKernel to support interactive R notebooks in Jupyter
# Note: We set the PATH to ensure that R knows were to find the 'jupyter' binary
# See IR kernel installation docs:
# https://irkernel.github.io/installation/
PATH="${CONDA_BIN_DIR}:${PATH}" "${RUN_R}" -e "\
install.packages('IRkernel', repos='http://cran.rstudio.com/');
IRkernel::installspec()"

# Add R to the PATH in user's bashrc
cat <<EOF >>"${USER_BASHRC}"
# Prepend "${R_BIN_DIR}" (if not already in the path)
if [[ ":\${PATH}:" != *":${R_BIN_DIR}:"* ]]; then
  export PATH="${R_BIN_DIR}":"\${PATH}"
fi
EOF
