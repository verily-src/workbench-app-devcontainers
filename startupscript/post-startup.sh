#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 user workDirectory <gcp/aws> <true/false>"
  exit 1
fi

readonly USER_NAME="${1}"
readonly WORK_DIRECTORY="${2}"
readonly CLOUD="${3}"
readonly LOG_IN="${4}"

# Gets absolute path of the script directory. 
# Because the script sometimes cd to other directoy (e.g. /tmp), 
# absolute path is more reliable.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
readonly SCRIPT_DIR
readonly CLOUD_SCRIPT_DIR="${SCRIPT_DIR}/${CLOUD}"
#######################################
# Emit a message with a timestamp
#######################################
source "${SCRIPT_DIR}/emit.sh"

source "${CLOUD_SCRIPT_DIR}/vm-metadata.sh"

readonly RUN_AS_LOGIN_USER="sudo -u ${USER_NAME} bash -l -c"

USER_PRIMARY_GROUP="$(id --group --name "${USER_NAME}")"
readonly USER_PRIMARY_GROUP
readonly USER_BASH_COMPLETION_DIR="${WORK_DIRECTORY}/.bash_completion.d"
readonly USER_HOME_LOCAL_SHARE="${WORK_DIRECTORY}/.local/share"
readonly USER_WORKBENCH_CONFIG_DIR="${WORK_DIRECTORY}/.workbench"
readonly USER_WORKBENCH_LEGACY_CONFIG_DIR="${WORK_DIRECTORY}/.terra"
readonly USER_BASHRC="${WORK_DIRECTORY}/.bashrc"
readonly USER_BASH_PROFILE="${WORK_DIRECTORY}/.bash_profile"
readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/post-startup-output.txt"

# Variables for Workbench-specific code installed on the VM
readonly WORKBENCH_INSTALL_PATH="/usr/bin/wb"
readonly WORKBENCH_LEGACY_PATH="/usr/bin/terra"
export WORKBENCH_INSTALL_PATH WORKBENCH_LEGACY_PATH

# Move to the /tmp directory to let any artifacts left behind by this script can be removed.
cd /tmp || exit

# Send stdout and stderr from this script to a file for debugging.
# Make the .workbench directory as the user so that they own it and have correct linux permissions.
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_WORKBENCH_CONFIG_DIR}'"
${RUN_AS_LOGIN_USER} "ln -sf '${USER_WORKBENCH_CONFIG_DIR}' '${USER_WORKBENCH_LEGACY_CONFIG_DIR}'"
exec >> "${POST_STARTUP_OUTPUT_FILE}"
exec 2>&1

# The apt package index may not be clean when we run; resynchronize
apt-get update
apt install -y jq curl fuse tar wget

# Create the target directories for installing into the HOME directory
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"


# Custom application behavior when opening a terminal window will vary.
#
# Some application that run in custom environments will by default run
# an interactive non-login shell, which sources the ~/.bashrc.
#
# Others will open a login shell, which sources the ~/.bash_profile.
#
# For consistency across these as many environments as possible, this startup
# script writes to  ~/.bashrc, and has the ~/.bash_profile source the ~/.bashrc

cat << EOF >> "${USER_BASH_PROFILE}"

if [[ -e ~/.bashrc ]]; then
 source ~/.bashrc
fi

EOF
chown "${USER_NAME}:${USER_PRIMARY_GROUP}" "${USER_BASH_PROFILE}"

# Indicate the start of Workbench customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"
### BEGIN: Workbench-specific customizations ###

# Prepend "/usr/bin" (if not already in the path)
if [[ "${PATH}:" != "/usr/bin:"* ]]; then
  export PATH=/usr/bin:${PATH}
fi
EOF

##################################################
# Set up java which is required for workbench CLI 
##################################################
source "${SCRIPT_DIR}/install-java.sh"

###################################
# Install workbench CLI
###################################
source "${SCRIPT_DIR}/install-cli.sh"

##################################################
# Set up user bashrc with workbench customization
##################################################
source "${SCRIPT_DIR}/setup-bashrc.sh"

#################
# bash completion
#################
source "${SCRIPT_DIR}/bash-completion.sh"

###############
# git setup
###############
if [[ "${LOG_IN}" == "true" ]]; then
    source "${SCRIPT_DIR}/git-setup.sh"
fi

#############################
# Mount buckets
#############################
source "${CLOUD_SCRIPT_DIR}/resource-mount.sh"

###############################
# cloud platform specific setup
###############################
if [[ -f "${CLOUD_SCRIPT_DIR}/post-startup-hook.sh" ]]; then
  source "${CLOUD_SCRIPT_DIR}/post-startup-hook.sh"
fi
