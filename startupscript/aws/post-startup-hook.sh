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
# - RUN_AS_LOGIN_USER: run command as app user
# - USER_BASH_PROFILE: path to user's ~/.bash_profile file
# - USER_BASHRC: path to user's ~/.bashrc file
# - USER_NAME: name of app user
# - USER_PRIMARY_GROUP: name of primary group app user belongs to
# - USER_WORKBENCH_CONFIG_DIR: user's WB configuration directory
# - WORK_DIRECTORY: home directory for the user that the script is running on behalf of
# - WORKBENCH_INSTALL_PATH: path to CLI executable

readonly AWS_VAULT_INSTALL_PATH="/usr/bin/aws-vault"
readonly AWS_VAULT_EXE_URL="https://github.com/99designs/aws-vault/releases/download/v7.2.0/aws-vault-linux-amd64"

##########################################
# Install aws-vault for credential caching
##########################################
emit "installing aws-vault"
curl --no-progress-meter --location --output "${AWS_VAULT_INSTALL_PATH}" "${AWS_VAULT_EXE_URL}"
chmod 755 "${AWS_VAULT_INSTALL_PATH}"

#####################################
# Set up aws-vault credential caching
#####################################
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set cache-with-aws-vault true"
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set wb-path --path ${WORKBENCH_INSTALL_PATH}"
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set aws-vault-path --path ${AWS_VAULT_INSTALL_PATH}"

#################################################
# Write common environment vars to user's .bashrc
#################################################
WORKBENCH_WORKSPACE_UUID="$(get_metadata_value_raw WorkspaceId)"
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
