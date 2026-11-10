#!/bin/bash

# setup-bashrc.sh
#
# Set variables into the .bashrc. In VIA's container the only reader is entrypoint.sh, which
# greps the exports into /root/.workbench-env before starting the app (see .devcontainer.json).
# The variable names follow upstream so that file looks the same as in any other Workbench app.
# 
# Keep in sync with Workbench CLI environment variables:
# https://github.com/verily-src/terra-tool-cli/blob/b146951ffc9c4f72f4d9c491a543b5c29bea3650/src/main/java/bio/terra/cli/app/CommandRunner.java#L94
#
# Note that this script is intended to be source from the "post-startup.sh" script 
# and is dependent on some variables and packages already being set up:
#
# - emit:  function to echo a message with a timestamp
# - USER_BASHRC: path to user's ~/.bashrc file
# - LOG_IN: whether the user is logged into the wb CLI as part of the script
# - RUN_AS_LOGIN_USER: run command as non-root Unix user (ex: jupyter, dataproc)
# - USER_WORKBENCH_CONFIG_DIR: where install-cli.sh leaves workspace.json
# 
# This script must be run after install-cli.sh

emit "Customize user bashrc ..."

if [[ "${LOG_IN}" == "true" ]]; then
  # The app reads two values from here (entrypoint.sh sources the exports): the Workbench user's
  # email and the workspace's GCP project. install-cli.sh's `workspace set` already fetched the
  # workspace description that carries both, so read its JSON; only describe (a ~10s call) when
  # that file isn't there, i.e. the VM had no workspace id in its metadata. Upstream describes
  # once per value and also records the pet service account via `auth status`; nothing here
  # reads that.
  readonly WORKSPACE_JSON_FILE="${USER_WORKBENCH_CONFIG_DIR}/workspace.json"
  if [[ -s "${WORKSPACE_JSON_FILE}" ]]; then
    WORKSPACE_JSON="$(cat "${WORKSPACE_JSON_FILE}")"
  else
    WORKSPACE_JSON="$(${RUN_AS_LOGIN_USER} "'${WORKBENCH_INSTALL_PATH}' workspace describe --format=json")"
  fi
  readonly WORKSPACE_JSON
  OWNER_EMAIL="$(jq --raw-output ".userEmail" <<< "${WORKSPACE_JSON}")"
  readonly OWNER_EMAIL
  GOOGLE_PROJECT="$(jq --raw-output ".googleProjectId" <<< "${WORKSPACE_JSON}")"
  readonly GOOGLE_PROJECT

  emit "Adding Workbench environment variables to ~/.bashrc ..."

  cat << EOF >> "${USER_BASHRC}"
# Set up a few legacy Workbench-specific convenience variables
export TERRA_USER_EMAIL='${OWNER_EMAIL}'
export OWNER_EMAIL='${OWNER_EMAIL}'

# Set up workbench-specific convenience variables
export WORKBENCH_USER_EMAIL='${OWNER_EMAIL}'

# Set up GCP specific legacy convenience variables
export GOOGLE_PROJECT='${GOOGLE_PROJECT}'
# Set up GCP specific convenience variables
export GOOGLE_CLOUD_PROJECT='${GOOGLE_PROJECT}'
EOF

else
  emit "User is not logged into workbench CLI."
fi
