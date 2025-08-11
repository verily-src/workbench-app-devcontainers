#!/bin/bash

# resource-mount.sh
#
# Installs goofys and mountpoint-s3 for s3 bucket mounting. The script cannot yet mount s3 bucket automatically
# because workbench CLI requires aws user to manually login.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function)
# - CLOUD_SCRIPT_DIR: path where AWS-specific scripts live
# - LOG_IN: whether the user is logged into workbench CLI
# - RUN_AS_LOGIN_USER: run command as user

# Install goofys
source "${CLOUD_SCRIPT_DIR}/install-goofys.sh"

# Install mountpoint-s3
source "${CLOUD_SCRIPT_DIR}/install-mountpoint-s3.sh"

if [[ "${LOG_IN}" == "true" ]]; then
  source "${CLOUD_SCRIPT_DIR}/configure-aws-vault.sh"
  ${RUN_AS_LOGIN_USER} "export AWS_VAULT_BACKEND='file' && \
    export AWS_VAULT_FILE_PASSPHRASE='' && \
    eval  \$(wb workspace configure-aws) && \
    wb resource mount || echo 'Resource mounting failed.'"
fi
