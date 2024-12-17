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
${RUN_AS_LOGIN_USER} "gcloud config set compute/region '${INSTANCE_REGION}'"
