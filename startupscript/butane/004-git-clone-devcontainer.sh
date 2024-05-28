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
else
    if [[ $# -eq 2 ]]; then
        readonly GIT_BRANCH="$2"
        git clone "${REPO_SRC}" -b "${GIT_BRANCH}" "${LOCAL_REPO}"
    else
        git clone "${REPO_SRC}" "${LOCAL_REPO}"
    fi
fi
