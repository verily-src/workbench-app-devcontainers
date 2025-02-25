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
# - WORKBENCH_LEGACY_PATH: path to the legacy cli name.
# - USER_BASH_COMPLETION_DIR: path to the bash completion file
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
    "verily") echo "https://terra-axon.api.verily.com/version" ;;
    "verily-devel") echo "https://terra-devel-axon.api.verily.com/version" ;;
    "verily-autopush") echo "https://terra-autopush-axon.api.verily.com/version" ;;
    "verily-staging") echo "https://terra-staging-axon.api.verily.com/version" ;;
    "verily-preprod") echo "https://terra-preprod-axon.api.verily.com/version" ;;
    "dev-stable") echo "https://workbench-dev.verily.com/api/axon/version" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/axon/version" ;;
    "test") echo "https://workbench-test.verily.com/api/axon/version" ;;
    "staging") echo "https://workbench-staging.verily.com/api/axon/version" ;;
    "prod") echo "https://workbench-prod.verily.com/api/axon/version" ;;
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
if ! command -v wb &> /dev/null; then
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

  # Copy 'wb' to its legacy 'terra' name.
  cp "${WORKBENCH_INSTALL_PATH}" "${WORKBENCH_LEGACY_PATH}"
fi

# Set browser manual login since that's the only login supported from a Vertex AI Notebook VM
${RUN_AS_LOGIN_USER} "wb config set browser MANUAL"

# Set the CLI server based on the server that created the VM.
${RUN_AS_LOGIN_USER} "wb server set --name=${TERRA_SERVER}"

# Generate the bash completion script
${RUN_AS_LOGIN_USER} "wb generate-completion > '${USER_BASH_COMPLETION_DIR}/workbench'"

if [[ "${LOG_IN}" == "true" ]]; then

  # For GCP use "APP_DEFAULT_CREDENTIALS", for AWS use "AWS_IAM" as --mode arg to "wb auth login".
  LOG_IN_MODE="APP_DEFAULT_CREDENTIALS"
  if [[ "${CLOUD}" == "aws" ]]; then
    LOG_IN_MODE="AWS_IAM"
  fi
  readonly LOG_IN_MODE

  # Log in with app-default-credentials
  emit "Logging into workbench CLI with mode ${LOG_IN_MODE}"
  ${RUN_AS_LOGIN_USER} "wb auth login --mode=${LOG_IN_MODE}"

  # Set the CLI workspace id using the VM metadata, if set.
  TERRA_WORKSPACE="$(get_metadata_value "terra-workspace-id")"
  readonly TERRA_WORKSPACE
  if [[ -n "${TERRA_WORKSPACE}" ]]; then
    ${RUN_AS_LOGIN_USER} "wb workspace set --id='${TERRA_WORKSPACE}'"
  fi
else
  emit "Do not log user into workbench CLI. Manual log in is required."
fi
