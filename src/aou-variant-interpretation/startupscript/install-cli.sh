#!/bin/bash

# install-cli.sh
#
#
# Install & configure the Workbench CLI
#
# Note that this script is dependent on some functions and variables already being set up in "post-startup.sh":
#
# - get_metadata_value (function)
# - RUN_AS_LOGIN_USER: run command as app user
# - WORKBENCH_INSTALL_PATH: path to install workbench cli
# - USER_WORKBENCH_CONFIG_DIR: where the workspace JSON is left for setup-bashrc.sh
# - WORKBENCH_LEGACY_PATH: path to the legacy cli name.
# - LOG_IN: whether to log in to CLI

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

source "${SCRIPT_DIR}/emit.sh"
source "${CLOUD_SCRIPT_DIR}/vm-metadata.sh"

# Map the CLI server to appropriate AFS service path and fetch the CLI distribution path
function get_axon_version_url() {
  case "$1" in
    "verily") echo "https://workbench.verily.com/api/axon/version" ;;
    "dev-stable") echo "https://workbench-dev.verily.com/api/axon/version" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/axon/version" ;;
    "test") echo "https://workbench-test.verily.com/api/axon/version" ;;
    "prod") echo "https://workbench.verily.com/api/axon/version" ;;
    *) return 1 ;;
  esac
}
readonly -f get_axon_version_url

# Fetch the Workbench CLI server environment from the metadata server to install appropriate CLI version
TERRA_SERVER="$(get_metadata_value "terra-cli-server")"
if [[ -z "${TERRA_SERVER}" ]]; then
  TERRA_SERVER="verily"
fi
readonly TERRA_SERVER

# Only install cli if not already installed
if ! command -v "${WORKBENCH_INSTALL_PATH}" &> /dev/null; then
  emit "Installing the Workbench CLI ..."

  if ! AXON_VERSION_URL="$(get_axon_version_url "${TERRA_SERVER}")"; then
    >&2 echo "ERROR: ${TERRA_SERVER} is not a known Workbench server"
    exit 1
  fi
  readonly AXON_VERSION_URL

  if ! VERSION_JSON="$(curl -s "${AXON_VERSION_URL}")"; then
    >&2 echo "ERROR: Failed to get version file from ${AXON_VERSION_URL}"
    exit 1
  fi
  readonly VERSION_JSON

  CLI_DISTRIBUTION_PATH="$(echo "${VERSION_JSON}" | jq -r '.cliDistributionPath')"
  readonly CLI_DISTRIBUTION_PATH

  CLI_VERSION="$(echo "${VERSION_JSON}" | jq -r '.latestSupportedCli')"
  readonly CLI_VERSION

  ${RUN_AS_LOGIN_USER} "curl -L https://storage.googleapis.com/${CLI_DISTRIBUTION_PATH#gs://}/download-install.sh | WORKBENCH_CLI_VERSION=${CLI_VERSION} bash"
  cp wb "${WORKBENCH_INSTALL_PATH}"
  chmod 755 "${WORKBENCH_INSTALL_PATH}"

  # Copy 'wb' to its legacy 'terra' name.
  cp wb "${WORKBENCH_LEGACY_PATH}"
  chmod 755 "${WORKBENCH_LEGACY_PATH}"
fi

# Every wb call is a cold JVM start of several seconds, so only the ones the login and the
# workspace lookup in setup-bashrc.sh depend on are made. Upstream also sets the browser login
# mode and generates shell completion here; neither matters in a container nobody opens a shell in.

# Set the CLI server based on the server that created the VM.
${RUN_AS_LOGIN_USER} "'${WORKBENCH_INSTALL_PATH}' server set --name=${TERRA_SERVER}"

if [[ "${LOG_IN}" == "true" ]]; then

  # Log in with the VM's attached service account (the user's pet SA).
  readonly LOG_IN_MODE="APP_DEFAULT_CREDENTIALS"

  # Log in with app-default-credentials
  emit "Logging into workbench CLI with mode ${LOG_IN_MODE}"
  ${RUN_AS_LOGIN_USER} "'${WORKBENCH_INSTALL_PATH}' auth login --mode=${LOG_IN_MODE}"

  # Set the CLI workspace id using the VM metadata, if set. `workspace set` returns the same
  # description `workspace describe` would, and each is a ~10s round trip, so its JSON is kept
  # for setup-bashrc.sh to read the user email and project from instead of describing again.
  TERRA_WORKSPACE="$(get_metadata_value "terra-workspace-id")"
  readonly TERRA_WORKSPACE
  if [[ -n "${TERRA_WORKSPACE}" ]]; then
    ${RUN_AS_LOGIN_USER} "'${WORKBENCH_INSTALL_PATH}' workspace set --id='${TERRA_WORKSPACE}' --format=json > '${USER_WORKBENCH_CONFIG_DIR}/workspace.json'"
  fi
else
  emit "Do not log user into workbench CLI. Manual log in is required."
fi
