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

if ! git ls-remote ${REPO_SRC} &> /dev/null; then
  set +o xtrace
  # private repo or repo does not exist
  response=$(curl https://workbench-dev.verily.com/api/ecm/api/oauth/v1/github/access-token \
  -w "\n%{http_code}" \
  -H "Authorization: Bearer $(/home/core/wb.sh auth print-access-token)")
  http_code=$(echo "${response}" | tail -n1)
  if [[ ${http_code} -eq 404 ]]; then
    # github account not linked
    exit 1
  elif [[ ${http_code} -eq 401 ]]; then
    # authorization issues
    exit 2
  elif [[ ${http_code} -ne 200 ]]; then
    # Failed to clone Git repository with http status: $response
    exit 3
  fi

  token=$(echo "${response}" | head -n1)
  # Insert token into url
  repo_auth_url=$(echo "${REPO_SRC}" | sed "s/:\/\//:\/\/${token}@/")

  git clone "${repo_auth_url}" "${LOCAL_REPO}"

  set -o xtrace
else
  git clone "${REPO_SRC}" "${LOCAL_REPO}"
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