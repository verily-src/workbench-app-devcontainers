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


# Map the server to appropriate service path
function get_service_url() {
  case "$1" in
    "dev-stable") echo "https://workbench-dev.verily.com/api/$2" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/$2" ;;
    "test") echo "https://workbench-test.verily.com/api/$2" ;;
    "prod") echo "https://workbench.verily.com/api/$2" ;;
    *) return 1 ;;
  esac
}
readonly -f get_service_url

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

trap 'rm -rf ${LOCAL_REPO}' ERR

PRIVATE_DEVCONTAINER_ENABLED="$(get_metadata_value "private-devcontainer-enabled" "")"
# Replace ssh URL with HTTPS URL
https_url="${REPO_SRC/git@github.com:/https://github.com/}"
# Create GitHub API URL
api_url="https://api.github.com/repos/${https_url/https:\/\/github.com\//}"
api_url="${api_url%.git}"
# Check if repo is private
private_status=$(curl --retry 5 -s "${api_url}" | jq -r ".status")
if [[ "${PRIVATE_DEVCONTAINER_ENABLED}" == "TRUE" && "${private_status}" == 404 ]]; then
  # Get ECM service URL
  SERVER="$(get_metadata_value "terra-cli-server" "")"
  readonly SERVER
  if [[ -z "${SERVER}" ]]; then
    SERVER="prod"
  fi
  if ! ECM_SERVICE_URL="$(get_service_url "${SERVER}" "ecm")"; then
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

  token=$(echo "${response}" | head -n1)
  # Insert token into url
  repo_auth_url=$(echo "${https_url}" | sed "s/:\/\//:\/\/${token}@/")

  # Clone the private repo
  set +o errexit
  response=$(git clone "${repo_auth_url}" "${LOCAL_REPO}" 2>&1)
  git_status=$?
  set -o errexit
  if [[ ${git_status} -ne 0 ]]; then
    set_metadata "startup_script/status" "ERROR"
    set_metadata "startup_script/message" "Failed to clone the devcontainer GitHub repo. ERROR: ${response}"
    exit 1
  fi

  # re-enable logs
  set -o xtrace
else
  # GitHub repo is public
  set +o errexit
  response=$(git clone "${REPO_SRC}" "${LOCAL_REPO}" 2>&1)
  git_status=$?
  set -o errexit
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