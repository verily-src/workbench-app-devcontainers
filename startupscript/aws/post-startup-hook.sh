#!/bin/bash -x

# post-startup-hook.sh
#
# Performs additional one-time configuration for applications running in AWS
# EC2 instances.
#
# Note that this script is intended to be sourced from the "post-startup.sh"
# script and is dependent on some functions and variables already being set up
# and some packages already installed:
#
# - aws (cli from ghcr.io/devcontainers/features/aws-cli:1)
# - emit (function)
# - CLOUD_SCRIPT_DIR: path where AWS-specific scripts live
# - USER_BASH_PROFILE: path to user's ~/.bash_profile file
# - USER_BASHRC: path to user's ~/.bashrc file
# - USER_NAME: name of app user
# - USER_PRIMARY_GROUP: name of primary group app user belongs to
# - USER_WORKBENCH_CONFIG_DIR: user's WB configuration directory
# - WORK_DIRECTORY: home directory for the user that the script is running on behalf of
# - WORKBENCH_INSTALL_PATH: path to CLI executable

if [[ "${LOG_IN}" == "true" ]]; then
    emit "Already logged in, skipping additional AWS configuration."
    exit 0
fi

########################################################
# Install and configure aws-vault for credential caching
########################################################
source "${CLOUD_SCRIPT_DIR}/configure-aws-vault.sh"

#################################################
# Write common environment vars to user's .bashrc
#################################################
WORKBENCH_WORKSPACE_UUID="$(get_metadata_value_unprefixed WorkspaceId)"
readonly WORKBENCH_WORKSPACE_UUID
AWS_CONFIG_FILE="${USER_WORKBENCH_CONFIG_DIR}/aws/${WORKBENCH_WORKSPACE_UUID}.conf"
readonly AWS_CONFIG_FILE

cat > "${USER_BASHRC}" << EOF

# AWS-specific Workbench Configuration Environment Variables
export WORKBENCH_WORKSPACE_UUID="${WORKBENCH_WORKSPACE_UUID}"
export WORKBENCH_GIT_REPOS_DIR="${WORK_DIRECTORY}/repos"
export WORKBENCH_INSTALL_PATH="${WORKBENCH_INSTALL_PATH}"
export AWS_CONFIG_FILE="${AWS_CONFIG_FILE}"
export AWS_VAULT_BACKEND="file"
export AWS_VAULT_FILE_PASSPHRASE=""
EOF

#######################################
# Write VWB helper functions to .bashrc
#######################################
cat "${CLOUD_SCRIPT_DIR}/bashrc-functions.bash" >> "${USER_BASHRC}"

##################################
# Write login prompt .bash_profile
##################################
cat "${CLOUD_SCRIPT_DIR}/bash-profile-append.bash" >> "${USER_BASH_PROFILE}"
