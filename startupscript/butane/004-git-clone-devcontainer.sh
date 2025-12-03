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

source /home/core/service-utils.sh
source /home/core/metadata-utils.sh

# Run a git command with error handling
# Args:
#   $1+: Git command and arguments
function run_git_command {
  local response

  if ! response=$(GIT_TERMINAL_PROMPT=0 "$@" 2>&1); then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone devcontainer GitHub repo. ERROR: ${response}"
    return 1
  fi
}

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

# Remove devcontainer repo on error
trap 'rm -rf ${LOCAL_REPO}' ERR
# Remove git credentials file on exit
GIT_CREDENTIALS_FILE="/tmp/.git-credentials"
trap 'rm -f ${GIT_CREDENTIALS_FILE}' EXIT

PRIVATE_DEVCONTAINER_ENABLED="$(get_metadata_value "private-devcontainer-enabled" "")"
# Replace GitHub SSH URL with HTTPS URL
HTTPS_URL="${REPO_SRC/git@github.com:/https://github.com/}"
# Create GitHub API URL
GITHUB_API_URL="https://api.github.com/repos/${HTTPS_URL/https:\/\/github.com\//}"
GITHUB_API_URL="${GITHUB_API_URL%.git}"
# Check if repo is private
private_status=$(curl -s -o /dev/null -w "%{http_code}" "${GITHUB_API_URL}")
if [[ "${PRIVATE_DEVCONTAINER_ENABLED}" == "TRUE" && "${private_status}" == 404 ]]; then
  # Get ECM service URL
  SERVER="$(get_metadata_value "terra-cli-server" "prod")"
  if ! ECM_SERVICE_URL="$(get_service_url "ecm" "${SERVER}")"; then
    exit 1
  fi

  # disable logs to not expose access token
  set +o xtrace

  # Retrieve GitHub access token
  response=$(curl "${ECM_SERVICE_URL}/api/oauth/v1/github/access-token" \
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

  TOKEN=$(echo "${response}" | head -n1)
  USERNAME=$(curl -H "Authorization: Bearer ${TOKEN}" https://api.github.com/user | jq --raw-output ".login")
  echo "https://${USERNAME}:${TOKEN}@github.com" > "${GIT_CREDENTIALS_FILE}"
  git config --system credential.helper "store --file=${GIT_CREDENTIALS_FILE}"

  # re-enable logs
  set -o xtrace
fi

# Clone the private or public repo
run_git_command git clone "${HTTPS_URL}" "${LOCAL_REPO}"

if [[ $# -eq 2 ]]; then
    readonly GIT_REF="$2"
    pushd "${LOCAL_REPO}"
    if git show-ref --verify --quiet "refs/heads/${GIT_REF}"; then
      # this is a local branch
      run_git_command git switch --detach "${GIT_REF}"
    elif git show-ref --verify --quiet "refs/remotes/origin/${GIT_REF}"; then
      # this is a remote branch
      run_git_command git switch --detach "origin/${GIT_REF}"
    else
      # this is a commit hash or tag
      run_git_command git switch --detach "${GIT_REF}"
    fi
    popd
fi

# Init & update submodules
(
  cd "${LOCAL_REPO}"
  run_git_command git submodule update --init --recursive
)