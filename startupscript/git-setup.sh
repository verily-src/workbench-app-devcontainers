#!/bin/bash

# git-setup.sh
#
# Configures workbench user's ssh private key in the app container and clones
# all the current Workbench workspace's git repo referenced resources into the repos/ 
# folder.
#
# Note that this script is intended to be source from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function)
# - Workbench CLI is installed
# - git is installed in the image or as a devcontainer feature (ghcr.io/devcontainers/features/git:1)
# - USER_SSH_DIR: path to ssh directory (~/.ssh)
# - WORKBENCH_GIT_REPOS_DIR: path to the git repo directory (~/repos)
# - RUN_AS_LOGIN_USER: run command as app user

emit "Setting up git integration..."

# Create the user SSH directory
${RUN_AS_LOGIN_USER} "mkdir -p ${USER_SSH_DIR} --mode 0700"

# Get the user's SSH key from Workbench, and if set, write it to the user's .ssh directory
${RUN_AS_LOGIN_USER} "\
 install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa.tmp' && \
 wb security ssh-key get --include-private-key --format=JSON >> '${USER_SSH_DIR}/id_rsa.tmp' || true"
if [[ -s "${USER_SSH_DIR}/id_rsa.tmp" ]]; then
 ${RUN_AS_LOGIN_USER} "\
   install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa' && \
   jq -r '.privateSshKey' '${USER_SSH_DIR}/id_rsa.tmp' > '${USER_SSH_DIR}/id_rsa'"
fi
rm -f "${USER_SSH_DIR}/id_rsa.tmp"

# Set the github known_hosts
apt-get update
apt-get install -y openssh-client
${RUN_AS_LOGIN_USER} "ssh-keyscan -H github.com >> '${USER_SSH_DIR}/known_hosts'"

# Create git repos directory
${RUN_AS_LOGIN_USER} "mkdir -p '${WORKBENCH_GIT_REPOS_DIR}'"

# Attempt to clone all the git repo references in the workspace. If the user's ssh key does not exist or doesn't have access
# to the git references, the corresponding git repo cloning will be skipped.
# Keep this as last thing in script. There will be integration test for git cloning (PF-1660). If this is last thing, then
# integration test will ensure that everything in script worked.
${RUN_AS_LOGIN_USER} "cd '${WORKBENCH_GIT_REPOS_DIR}' && wb git clone --all"

