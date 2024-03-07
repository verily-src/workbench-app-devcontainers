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

##########################################
# Install aws-vault for credential caching
##########################################
emit "installing aws-vault"
curl --no-progress-meter --location --output "${AWS_VAULT_INSTALL_PATH}" \
    https://github.com/99designs/aws-vault/releases/download/v7.2.0/aws-vault-linux-amd64
chmod 755 "${AWS_VAULT_INSTALL_PATH}"

#####################################
# Set up aws-vault credential caching
#####################################
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set cache-with-aws-vault true"
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set wb-path --path ${WORKBENCH_INSTALL_PATH}"
${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} config set aws-vault-path --path ${AWS_VAULT_INSTALL_PATH}"

###############################################################################
# Write common environment vars to .profile so they are present in all contexts
###############################################################################
WORKBENCH_WORKSPACE="$(get_metadata_value terra-workspace-id)"
readonly WORKBENCH_WORKSPACE
readonly AWS_CONFIG_FILE="${USER_WORKBENCH_CONFIG_DIR}/aws/${WORKBENCH_WORKSPACE}.conf"
cat >> "${USER_PROFILE}" << EOF
### BEGIN: Workbench AWS-specific customizations ###
export WORKBENCH_WORKSPACE="${WORKBENCH_WORKSPACE}"
export WORKBENCH_GIT_REPOS_DIR="${WORKBENCH_GIT_REPOS_DIR}"
export WORKBENCH_INSTALL_PATH="${WORKBENCH_INSTALL_PATH}"
export AWS_CONFIG_FILE="${AWS_CONFIG_FILE}"
export AWS_VAULT_BACKEND="file"
export AWS_VAULT_FILE_PASSPHRASE=""
EOF
chown "${USER_NAME}:${USER_PRIMARY_GROUP}" "${USER_PROFILE}"

#######################################
# Write VWB helper functions to .bashrc
#######################################
cat >> "${USER_BASHRC}" << 'EOF'

function configure_workspace() {
  "${WORKBENCH_INSTALL_PATH}" workspace set --uuid "${WORKBENCH_WORKSPACE}"
  "${WORKBENCH_INSTALL_PATH}" workspace configure-aws --cache-with-aws-vault=true
  "${WORKBENCH_INSTALL_PATH}" resource mount
}
readonly -f configure_workspace

function configure_ssh() {
  local USER_SSH_DIR="${HOME}/.ssh"
  mkdir -p ${USER_SSH_DIR}
  local USER_SSH_KEY="$("${WORKBENCH_INSTALL_PATH}" security ssh-key get --include-private-key --format=JSON)"
  echo "${USER_SSH_KEY}" | jq -r '.privateSshKey' > "${USER_SSH_DIR}"/id_rsa
  echo "${USER_SSH_KEY}" | jq -r '.publicSshKey' > "${USER_SSH_DIR}"/id_rsa.pub
  chmod 0600 "${USER_SSH_DIR}"/id_rsa*
  ssh-keyscan -H github.com >> ${USER_SSH_DIR}/known_hosts
}
readonly -f configure_ssh

function configure_git() {
  mkdir -p "${WORKBENCH_GIT_REPOS_DIR}"
  pushd "${WORKBENCH_GIT_REPOS_DIR}"
  "${WORKBENCH_INSTALL_PATH}" resource list --type=GIT_REPO --format json | \
    jq -c .[] | \
    while read ITEM; do
      local GIT_REPO_NAME="$(echo $ITEM | jq -r .id)"
      local GIT_REPO_URL="$(echo $ITEM | jq -r .gitRepoUrl)"
      if [[ ! -d "${GIT_REPO_NAME}" ]]; then
        git clone "${GIT_REPO_URL}" "${GIT_REPO_NAME}"
      fi
    done
  popd
}
readonly -f configure_git

function configure_workbench() {
  configure_workspace
  configure_ssh
  configure_git
}
readonly -f configure_workbench
EOF

##################################
# Write login prompt .bash_profile
##################################
cat >> "${USER_BASH_PROFILE}" << 'EOF'

if [[ "$("${WORKBENCH_INSTALL_PATH}" auth status --format json | jq .loggedIn)" == false ]]; then
    echo "User must log into Workbench to continue."
    "${WORKBENCH_INSTALL_PATH}" auth login
    configure_workbench
fi
EOF
