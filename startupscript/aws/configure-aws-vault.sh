#!/bin/bash -x

# configure-aws-vault.sh
#
# Performs additional one-time configuration for applications running in AWS
# EC2 instances.
#
# Note that this script is intended to be sourced from the "post-startup.sh"
# script and is dependent on some functions and variables already being set up
# and some packages already installed:
#
# - emit (function)
# - RUN_AS_LOGIN_USER: run command as app user
# - WORKBENCH_INSTALL_PATH: path to CLI executable

readonly AWS_VAULT_INSTALL_PATH="/usr/bin/aws-vault"
readonly AWS_VAULT_EXE_URL="https://github.com/99designs/aws-vault/releases/download/v7.2.0/aws-vault-linux-amd64"

if [[ -f "${AWS_VAULT_INSTALL_PATH}" ]]; then
    emit "aws-vault already installed"
else
    ##########################################
    # Install aws-vault for credential caching
    ##########################################
    emit "installing aws-vault"
    curl --no-progress-meter --location --output "${AWS_VAULT_INSTALL_PATH}" "${AWS_VAULT_EXE_URL}"
    chmod 755 "${AWS_VAULT_INSTALL_PATH}"

    ##########################################
    # Export AWS-related environment variables
    ##########################################
    export AWS_VAULT_BACKEND="file"
    export AWS_VAULT_FILE_PASSPHRASE=""

    #####################################
    # Set up aws-vault credential caching
    #####################################
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set cache-with-aws-vault true"
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set wb-path --path ${WORKBENCH_INSTALL_PATH}"
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set aws-vault-path --path ${AWS_VAULT_INSTALL_PATH}"
fi
