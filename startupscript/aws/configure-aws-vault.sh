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
readonly AWS_VAULT_BINARY_PATH="/usr/bin/_aws-vault"
readonly AWS_VAULT_EXE_URL="https://github.com/ByteNess/aws-vault/releases/download/v7.9.13/aws-vault-linux-amd64"

if [[ -f "${AWS_VAULT_INSTALL_PATH}" ]]; then
    emit "aws-vault already installed"
else
    ##########################################
    # Install aws-vault for credential caching
    ##########################################
    emit "installing aws-vault"
    curl --no-progress-meter --location --output "${AWS_VAULT_BINARY_PATH}" "${AWS_VAULT_EXE_URL}"

    cat <<EOF > "${AWS_VAULT_INSTALL_PATH}"
export AWS_VAULT_BACKEND="file"
export AWS_VAULT_FILE_PASSPHRASE=""

# aws-vault's keyring dependency creates dbus-daemon processes without cleaning
# them up (https://github.com/99designs/keyring/issues/103). By setting
# DBUS_SESSION_BUS_ADDRESS to /dev/null, we can prevent aws-vault from creating
# these processes. dbus is only needed for the "secretservice" backend, which we
# do not use.
export DBUS_SESSION_BUS_ADDRESS="/dev/null"

exec "${AWS_VAULT_BINARY_PATH}" "\$@"
EOF

    chmod 755 "${AWS_VAULT_INSTALL_PATH}"
    chmod 755 "${AWS_VAULT_BINARY_PATH}"

    #####################################
    # Set up aws-vault credential caching
    #####################################
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set cache-with-aws-vault true"
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set wb-path --path ${WORKBENCH_INSTALL_PATH}"
    ${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set aws-vault-path --path ${AWS_VAULT_INSTALL_PATH}"
fi
