#!/bin/bash

# install-cli.sh
#
#
# Install & configure the Workbench CLI
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up:
#
# - emit (function)
# - get_metadata_value (function)
# - RUN_AS_LOGIN_USER: run command as app user 
# - WORKBENCH_INSTALL_PATH: path to install workbench cli
# - WORKBENCH_LEGACY_PATH: path to the legacy cli name.
# - USER_BASH_COMPLETION_DIR: path to the bash completion file
# - LOG_IN: whether to log in to CLI

emit "Installing the Workbench CLI ..."

# Fetch the Workbench CLI server environment from the metadata server to install appropriate CLI version
TERRA_SERVER="$(get_metadata_value "terra-cli-server")"
if [[ -z "${TERRA_SERVER}" ]]; then
  TERRA_SERVER="verily"
fi
readonly TERRA_SERVER

# If the server environment is a verily server, use the verily download script.
if [[ "${TERRA_SERVER}" == *"verily"* ]]; then
  # Map the CLI server to appropriate AFS service path and fetch the CLI distribution path
  if ! versionJson="$(curl -s "https://${TERRA_SERVER/verily/terra}-axon.api.verily.com/version")"; then
    >&2 echo "ERROR: Failed to get version file from ${TERRA_SERVER}"
    exit 1
  fi
  cliDistributionPath="$(echo "${versionJson}" | jq -r '.cliDistributionPath')"

  ${RUN_AS_LOGIN_USER} "curl -L https://storage.googleapis.com/${cliDistributionPath#gs://}/download-install.sh | TERRA_CLI_SERVER=${TERRA_SERVER} bash"
  cp wb "${WORKBENCH_INSTALL_PATH}"
else
  >&2 echo "ERROR: ${TERRA_SERVER} is not a known Workbench server"
  exit 1
fi

# Copy 'wb' to its legacy 'terra' name.
cp "${WORKBENCH_INSTALL_PATH}" "${WORKBENCH_LEGACY_PATH}"

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
