#!/bin/bash

# git-clone-devcontainer.sh clones a Git repository to the VM. If branch is specified, clones the specific branch.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <git_url> [branch_name]"
  echo "  git_url: The URL of the Git repository to clone."
  echo "  branch_name (optional): The specific branch to clone."
  exit 1
}
if [[ $# -lt 1 ]]; then
    usage
fi

source /home/core/metadata-utils.sh

# To accommodate the use of SSH URLs for public Git repositories, set the following Git configuration:
# Note: This script is to be run as root on Flatcar Linux. We need to set system config instead of global config because
# the latter requires $HOME to be set and root is $HOME-less.
git config --system url.https://github.com/.insteadOf git@github.com:

readonly REPO_SRC="$1"
readonly LOCAL_REPO=/home/core/devcontainer
# Skip on reboot when the devcontainer is already cloned. Because we modify devcontainer template after cloning, pulling
# will fail.
if [[ -d "${LOCAL_REPO}/.git" ]]; then
    echo "Git repo already exists, skip cloning..."
    exit 0
fi

PRIVATE_DEVCONTAINER_ENABLED="$(get_metadata_value "private-devcontainer-enabled" "")"
# Check if repo is private by attempting to list files
if [[ "${PRIVATE_DEVCONTAINER_ENABLED}" = "TRUE" ]] && ! git ls-remote "${REPO_SRC}" &> /dev/null; then
  # disable logs
  set +o xtrace

  # Retrieve GitHub access token
  response=$(curl https://workbench-dev.verily.com/api/ecm/api/oauth/v1/github/access-token \
  -w "\n%{http_code}" \
  -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)")
  http_code=$(echo "${response}" | tail -n1)
  body=$(echo "${response}" | head -n -1)
  if [[ ${http_code} -eq 404 ]]; then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone the devcontainer GitHub repo. Please verify your GitHub account is linked and try recreating the VM."
    exit 1
  elif [[ ${http_code} -ne 200 ]]; then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone the devcontainer GitHub repo. ERROR: ${body}."
    exit 1
  fi

  token=$(echo "${response}" | head -n1)
  # Insert token into url
  repo_auth_url=$(echo "${REPO_SRC}" | sed "s/:\/\//:\/\/${token}@/")

  # Clone the private repo
  response=$(git clone "${repo_auth_url}" "${LOCAL_REPO}" 2>&1)
  git_status=$?
  if [[ ${git_status} -ne 0 ]]; then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone the devcontainer GitHub repo. ERROR: ${response}"
    exit 1
  fi

  # re-enable logs
  set -o xtrace
else
  # GitHub repo is public
  response=$(git clone "${REPO_SRC}" "${LOCAL_REPO}" 2>&1)
  git_status=$?
  if [[ ${git_status} -ne 0 ]]; then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone the devcontainer GitHub repo. ERROR: ${response}"
    exit 1
  fi
fi

if [[ $# -eq 2 ]]; then
    readonly GIT_REF="$2"
    pushd "${LOCAL_REPO}"
    if git show-ref --verify --quiet "refs/heads/${GIT_REF}"; then
      # this is a local branch
      git switch --detach "${GIT_REF}"
    elif git show-ref --verify --quiet "refs/remotes/origin/${GIT_REF}"; then
      # this is a remote branch
      git switch --detach "origin/${GIT_REF}"
    else
      # this is a commit hash
      git switch --detach "${GIT_REF}"
    fi
    popd
fi