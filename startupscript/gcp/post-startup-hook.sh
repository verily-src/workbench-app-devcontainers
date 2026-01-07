#!/bin/bash -x

# post-startup-hook.sh
#
# Performs additional one-time configuration for applications running in GCP
# GCE instances.
#
# Note that this script is intended to be sourced from the "post-startup.sh"
# script and is dependent on some functions and variables already being set up
# and some packages already installed:
#
# - get_instance_region (function)
# - RUN_AS_LOGIN_USER: command prefix to run a command as the login user

# Set the gcloud region config to the VM's zone
INSTANCE_REGION="$(get_instance_region)"

# Check if gcloud is logged in and set the region if it is
ACCOUNT="$(${RUN_AS_LOGIN_USER} "gcloud config get-value account 2>/dev/null" | tr -d '[:space:]')"
if [[ "$ACCOUNT" != "(unset)" && -n "$ACCOUNT" ]]; then
  ${RUN_AS_LOGIN_USER} "gcloud config set compute/region '${INSTANCE_REGION}'"
else
  echo "gcloud is not logged in. Skipping region configuration."
fi
