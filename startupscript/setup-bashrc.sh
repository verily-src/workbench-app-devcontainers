#!/bin/bash

# setup-bashrc.sh
#
# Set variables into the .bashrc such that they are available to terminals, notebooks, and other tools. 
# We have new-style variables (eg WORKBENCH_USER_EMAIL) which are set here and CLI (terra app execute env). 
# We also support a few variables set for legacy reasons (eg GOOGLE_PROJECT). Those are only set here and 
# NOT in the CLI as they are intended just to make porting existing notebooks easier.
# 
# Keep in sync with Workbench CLI environment variables:
# https://github.com/verily-src/terra-tool-cli/blob/b146951ffc9c4f72f4d9c491a543b5c29bea3650/src/main/java/bio/terra/cli/app/CommandRunner.java#L94
#
# Note that this script is intended to be source from the "post-startup.sh" script 
# and is dependent on some variables and packages already being set up:
#
# - emit:  function to echo a message with a timestamp
# - USER_BASHRC: path to user's ~/.bashrc file
# - CLOUD: aws/gcp
# - LOG_IN: whether the user is logged into the wb CLI as part of the script
# - RUN_AS_LOGIN_USER: run command as non-root Unix user (ex: jupyter, dataproc)
# 
# This script must be run after install-cli.sh

emit "Customize user bashrc ..."

if [[ "${LOG_IN}" == "true" ]]; then
  # OWNER_EMAIL is really the Workbench user account email address
  readonly OWNER_EMAIL="$(
    ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
    jq --raw-output ".userEmail")"

  # PET_SA_EMAIL is the pet service account for the Workbench user and
  # is specific to the GCP project backing the workspace
  readonly PET_SA_EMAIL="$(
    ${RUN_AS_LOGIN_USER} "wb auth status --format=json" | \
    jq --raw-output ".serviceAccountEmail")"

  cat << EOF >> "${USER_BASHRC}"
# Set up a few legacy Workbench-specific convenience variables
export TERRA_USER_EMAIL='${OWNER_EMAIL}'
export OWNER_EMAIL='${OWNER_EMAIL}'
export PET_SA_EMAIL='${PET_SA_EMAIL}'

# Set up workbench-specific convenience variables
export WORKBENCH_USER_EMAIL='${OWNER_EMAIL}'
export GOOGLE_SERVICE_ACCOUNT_EMAIL='${PET_SA_EMAIL}'
EOF

else
  emit "User is not logged into workbench CLI."
fi

if [[ "${CLOUD}" == "gcp" && "${LOG_IN}" == "true" ]]; then

  # GOOGLE_PROJECT is the project id for the GCP project backing the workspace
  readonly GOOGLE_PROJECT="$(
    ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
    jq --raw-output ".googleProjectId")"
  
  emit "Adding Workbench GCP-sepcific environment variables to ~/.bashrc ..."

  cat << EOF >> "${USER_BASHRC}"

# Set up GCP specific legacy convenience variables
export GOOGLE_PROJECT='${GOOGLE_PROJECT}'
# Set up GCP specific convenience variables
export GOOGLE_CLOUD_PROJECT='${GOOGLE_PROJECT}'
EOF

fi


