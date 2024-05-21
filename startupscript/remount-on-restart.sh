#!/bin/bash

# remount-on-restart.sh
#
# Remounts buckets for the logged in user when a devcontainer instance is restarted.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 user workDirectory <gcp/aws> <true/false>"
  exit 1
fi

readonly USER_NAME="${1}"
readonly WORK_DIRECTORY="${2}"
readonly CLOUD="${3}"
# shellcheck disable=SC2034
readonly LOG_IN="${4}"

##############################################
# Get absolute paths of the script directories
##############################################
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
readonly SCRIPT_DIR
readonly CLOUD_SCRIPT_DIR="${SCRIPT_DIR}/${CLOUD}"

######################################################
# Change to /tmp to avoid leaving junk on file system.
######################################################
cd /tmp

##################################################################
# Send stdout and stderr from this script to a file for debugging.
##################################################################
readonly USER_WORKBENCH_CONFIG_DIR="${WORK_DIRECTORY}/.workbench"
readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/remount-on-restart-output.txt"
exec >> "${POST_STARTUP_OUTPUT_FILE}"
exec 2>&1

##############################
# Import utility functions
##############################
source "${SCRIPT_DIR}/emit.sh"

#############################
# Mount buckets
#############################
# shellcheck disable=SC2034
readonly RUN_AS_LOGIN_USER="sudo -u ${USER_NAME} bash -l -c"
source "${CLOUD_SCRIPT_DIR}/resource-mount.sh"
