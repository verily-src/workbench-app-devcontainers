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

echo "=== POST-STARTUP-HOOK.SH (GCP) STARTING ===" >&2

# Check if get_instance_region function exists
if declare -f get_instance_region > /dev/null; then
  echo "=== get_instance_region function is defined ===" >&2
else
  echo "=== ERROR: get_instance_region function is NOT defined ===" >&2
  exit 1
fi

# Check if RUN_AS_LOGIN_USER variable is set
if [[ -n "${RUN_AS_LOGIN_USER}" ]]; then
  echo "=== RUN_AS_LOGIN_USER is set to: ${RUN_AS_LOGIN_USER} ===" >&2
else
  echo "=== ERROR: RUN_AS_LOGIN_USER is NOT set ===" >&2
  exit 1
fi

# Set the gcloud region config to the VM's zone
echo "=== Attempting to get instance region from metadata server ===" >&2
INSTANCE_REGION="$(get_instance_region)"
echo "=== INSTANCE_REGION=${INSTANCE_REGION} ===" >&2

# Check if gcloud is logged in and set the region if it is
echo "=== Checking gcloud login status ===" >&2
ACCOUNT="$(${RUN_AS_LOGIN_USER} "gcloud config get-value account 2>/dev/null" | tr -d '[:space:]')"
echo "=== ACCOUNT=${ACCOUNT} ===" >&2
if [[ "$ACCOUNT" != "(unset)" && -n "$ACCOUNT" ]]; then
  echo "=== gcloud is logged in, setting region to ${INSTANCE_REGION} ===" >&2
  ${RUN_AS_LOGIN_USER} "gcloud config set compute/region '${INSTANCE_REGION}'"
  echo "=== Region set successfully ===" >&2
else
  echo "gcloud is not logged in. Skipping region configuration."
fi

echo "=== POST-STARTUP-HOOK.SH (GCP) COMPLETED SUCCESSFULLY ===" >&2
