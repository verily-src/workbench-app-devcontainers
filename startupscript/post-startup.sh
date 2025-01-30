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
export USER_NAME
readonly WORK_DIRECTORY="${2}"
export WORK_DIRECTORY
readonly CLOUD="${3}"
export CLOUD
readonly LOG_IN="${4}"
export LOG_IN

# Gets absolute path of the script directory.
# Because the script sometimes cd to other directoy (e.g. /tmp),
# absolute path is more reliable.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
readonly SCRIPT_DIR
export SCRIPT_DIR
readonly CLOUD_SCRIPT_DIR="${SCRIPT_DIR}/${CLOUD}"
export CLOUD_SCRIPT_DIR
#######################################
# Emit a message with a timestamp
#######################################
source "${SCRIPT_DIR}/emit.sh"

source "${CLOUD_SCRIPT_DIR}/vm-metadata.sh"

readonly RUN_AS_LOGIN_USER="sudo -u ${USER_NAME} bash -l -c"
export RUN_AS_LOGIN_USER

# Startup script status is propagated out to VM guest attributes
readonly STATUS_ATTRIBUTE="startup_script/status"
export STATUS_ATTRIBUTE
readonly MESSAGE_ATTRIBUTE="startup_script/message"
export MESSAGE_ATTRIBUTE

USER_PRIMARY_GROUP="$(id --group --name "${USER_NAME}")"
readonly USER_PRIMARY_GROUP
export USER_PRIMARY_GROUP
readonly USER_BASH_COMPLETION_DIR="${WORK_DIRECTORY}/.bash_completion.d"
export USER_BASH_COMPLETION_DIR
readonly USER_HOME_LOCAL_SHARE="${WORK_DIRECTORY}/.local/share"
export USER_HOME_LOCAL_SHARE
readonly USER_WORKBENCH_CONFIG_DIR="${WORK_DIRECTORY}/.workbench"
export USER_WORKBENCH_CONFIG_DIR
readonly USER_WORKBENCH_LEGACY_CONFIG_DIR="${WORK_DIRECTORY}/.terra"
export USER_WORKBENCH_LEGACY_CONFIG_DIR
readonly USER_BASHRC="${WORK_DIRECTORY}/.bashrc"
export USER_BASHRC
readonly USER_BASH_PROFILE="${WORK_DIRECTORY}/.bash_profile"
export USER_BASH_PROFILE
readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/post-startup-output.txt"
export POST_STARTUP_OUTPUT_FILE

# Variables for Workbench-specific code installed on the VM
readonly WORKBENCH_INSTALL_PATH="/usr/bin/wb"
export WORKBENCH_INSTALL_PATH
readonly WORKBENCH_LEGACY_PATH="/usr/bin/terra"
export WORKBENCH_LEGACY_PATH

# Move to the /tmp directory to let any artifacts left behind by this script can be removed.
cd /tmp || exit

# Send stdout and stderr from this script to a file for debugging.
# Make the .workbench directory as the user so that they own it and have correct linux permissions.
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_WORKBENCH_CONFIG_DIR}'"
${RUN_AS_LOGIN_USER} "ln -sf '${USER_WORKBENCH_CONFIG_DIR}' '${USER_WORKBENCH_LEGACY_CONFIG_DIR}'"
exec > >(tee -a "${POST_STARTUP_OUTPUT_FILE}")  # Append output to the file and print to terminal
exec 2> >(tee -a "${POST_STARTUP_OUTPUT_FILE}" >&2)  # Append errors to the file and print to terminal

# The apt package index may not be clean when we run; resynchronize
if type apk > /dev/null 2>&1; then
  apk update
  apk add --no-cache jq curl fuse tar wget
elif type apt-get > /dev/null 2>&1; then
  apt-get update
  apt install -y jq curl fuse tar wget
else
  >&2 echo "ERROR: Unable to find a supported package manager"
  exit 1
fi


# Create the target directories for installing into the HOME directory
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"


#######################################
# Set guest attributes on GCE. Used here to log completion status of the script.
# See https://cloud.google.com/compute/docs/metadata/manage-guest-attributes
# Arguments:
#   $1: The guest attribute domain and key IE startup_script/status
#   $2  The data to write to the guest attribute
#######################################
# If the script exits without error let the UI know it completed successfully
# Otherwise if an error occurred write the line and command that failed to guest attributes.
function exit_handler {
  local exit_code="${1}"
  local line_no="${2}"
  local command="${3}"
  # Success! Set the guest attributes and exit cleanly
  if [[ "${exit_code}" -eq 0 ]]; then
    exit 0
  fi
  # Write error status and message to guest attributes
  set_metadata "${STATUS_ATTRIBUTE}" "ERROR"
  set_metadata "${MESSAGE_ATTRIBUTE}" "There was an error in the VM Startup Script on line ${line_no}, command \"${command}\". Please try recreating the VM. See ${POST_STARTUP_OUTPUT_FILE} for more information."
  exit "${exit_code}"
}
readonly -f exit_handler
trap 'exit_handler $? $LINENO $BASH_COMMAND' EXIT

#######################################
# function to retry command
#######################################
function retry () {
  local max_attempts="$1"
  local command="$2"

  local attempt
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    # Run the command and return if success
    if ${command}; then
      return
    fi

    # Sleep a bit in case the problem is a transient network/server issue
    if ((attempt < max_attempts)); then
      echo "Retrying $(command) in 5 seconds" # send to get_message
      sleep 5
    fi
  done

  # Execute without the if/then protection such that the exit code propagates
  ${command}
}
readonly -f retry

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
if [[ "\${PATH}:" != "/usr/bin:"* ]]; then
  export PATH=/usr/bin:\${PATH}
fi
EOF

##################################################
# Set up java which is required for workbench CLI
##################################################
source "${SCRIPT_DIR}/install-java.sh"

###################################
# Install workbench CLI
###################################
retry 5 "${SCRIPT_DIR}/install-cli.sh"

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
    retry 5 "${SCRIPT_DIR}/git-setup.sh"
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
