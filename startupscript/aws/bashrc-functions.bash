
# Workbench helper functions for AWS. Note the lack of a shebang is 
# intentional. This file will be appended to the user's .bashrc file, and is
# kept separate so that these functions can be linted with shellcheck.

function configure_workspace() {
  "${WORKBENCH_INSTALL_PATH}" workspace set --uuid "${WORKBENCH_WORKSPACE_UUID}"
  "${WORKBENCH_INSTALL_PATH}" workspace configure-aws --cache-with-aws-vault=true
  "${WORKBENCH_INSTALL_PATH}" resource mount
}
readonly -f configure_workspace

function configure_ssh() {
  local USER_SSH_DIR="${HOME}/.ssh"
  mkdir -p "${USER_SSH_DIR}"
  local USER_SSH_KEY
  USER_SSH_KEY="$("${WORKBENCH_INSTALL_PATH}" security ssh-key get --include-private-key --format=JSON)"
  echo "${USER_SSH_KEY}" | jq -r '.privateSshKey' > "${USER_SSH_DIR}"/id_rsa
  echo "${USER_SSH_KEY}" | jq -r '.publicSshKey' > "${USER_SSH_DIR}"/id_rsa.pub
  chmod 0600 "${USER_SSH_DIR}"/id_rsa*
  ssh-keyscan -H github.com >> "${USER_SSH_DIR}/known_hosts"
}
readonly -f configure_ssh

function configure_git() {
  mkdir -p "${WORKBENCH_GIT_REPOS_DIR}"
  pushd "${WORKBENCH_GIT_REPOS_DIR}" || return
  "${WORKBENCH_INSTALL_PATH}" resource list --type=GIT_REPO --format json | \
    jq -c .[] | \
    while read -r ITEM; do
      local GIT_REPO_NAME
      GIT_REPO_NAME="$(echo "$ITEM" | jq -r .id)"
      local GIT_REPO_URL
      GIT_REPO_URL="$(echo "$ITEM" | jq -r .gitRepoUrl)"
      if [[ ! -d "${GIT_REPO_NAME}" ]]; then
        git clone "${GIT_REPO_URL}" "${GIT_REPO_NAME}"
      fi
    done
  popd || return
}
readonly -f configure_git

function configure_workbench() {
  configure_workspace
  configure_ssh
  configure_git
}
readonly -f configure_workbench
