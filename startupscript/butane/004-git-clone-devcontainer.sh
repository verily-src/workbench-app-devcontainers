#!/bin/bash

# git-clone-devcontainer.sh clones a Git repository to the VM. If branch is specified, clone the specific branch.
set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <git_url> <devcontainer_path> [branch_name]"
  echo "  git_url: The URL of the Git repository to clone."
  echo "  branch_name (optional): The specific branch to clone."
  exit 1
}
if [[ $# -lt 1 ]]; then
    usage
fi

git config --global url.https://github.com/.insteadOf git@github.com:
readonly REPO_SRC="$1"
readonly LOCAL_REPO=/home/core/devcontainer
if [[ $# -eq 2 ]]; then
    readonly GIT_BRANCH="$2"
    git clone "${REPO_SRC}" -b "${GIT_BRANCH}" "${LOCAL_REPO}" 2> /dev/null || git -C "${LOCAL_REPO}" pull
else
    git clone "${REPO_SRC}" "${LOCAL_REPO}" 2> /dev/null || git -C "${LOCAL_REPO}" pull
fi
