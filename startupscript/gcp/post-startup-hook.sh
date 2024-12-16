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
# - get_instance_zone (function)
# - CLOUD_SCRIPT_DIR: path where GCP-specific scripts live
# - USER_BASH_PROFILE: path to user's ~/.bash_profile file
# - USER_BASHRC: path to user's ~/.bashrc file
# - USER_NAME: name of app user
# - USER_PRIMARY_GROUP: name of primary group app user belongs to
# - USER_WORKBENCH_CONFIG_DIR: user's WB configuration directory
# - WORK_DIRECTORY: home directory for the user that the script is running on behalf of
# - WORKBENCH_INSTALL_PATH: path to CLI executable

# shellcheck source=/dev/null
source "${CLOUD_SCRIPT_DIR}/vm-metadata.sh"

# Set the gcloud zone config to the VM's zone
INSTANCE_ZONE="$(get_instance_zone)"
gcloud config set compute/zone "${INSTANCE_ZONE}"
