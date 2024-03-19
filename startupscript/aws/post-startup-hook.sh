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
# - WORKBENCH_GIT_REPOS_DIR: path to the git repo directory (~/repos)
# - WORKBENCH_INSTALL_PATH: path to CLI executable

readonly USER_PROFILE="${WORK_DIRECTORY}/.profile"
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

#######################################################################################
# Write common environment vars to /etc/environment so they are present in all contexts
#######################################################################################
WORKBENCH_WORKSPACE="$(get_metadata_value terra-workspace-id)"
readonly WORKBENCH_WORKSPACE
AWS_CONFIG_FILE="${USER_WORKBENCH_CONFIG_DIR}/aws/${WORKBENCH_WORKSPACE}.conf"
readonly AWS_CONFIG_FILE
cat >> /etc/environment << EOF
WORKBENCH_WORKSPACE="${WORKBENCH_WORKSPACE}"
WORKBENCH_GIT_REPOS_DIR="${WORKBENCH_GIT_REPOS_DIR}"
WORKBENCH_INSTALL_PATH="${WORKBENCH_INSTALL_PATH}"
AWS_CONFIG_FILE="${AWS_CONFIG_FILE}"
AWS_VAULT_BACKEND="file"
AWS_VAULT_FILE_PASSPHRASE=""
EOF
chown "${USER_NAME}:${USER_PRIMARY_GROUP}" "${USER_PROFILE}"

#######################################
# Write VWB helper functions to .bashrc
#######################################
cat "${CLOUD_SCRIPT_DIR}/bashrc-functions.bash" >> "${USER_BASHRC}"

##################################
# Write login prompt .bash_profile
##################################
cat "${CLOUD_SCRIPT_DIR}/bash-profile-append.bash" >> "${USER_BASH_PROFILE}"
