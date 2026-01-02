#!/bin/bash

# check-for-newer-os-update.sh - Flatcar Double-Update Workaround and Metadata Cleanup
#
# This script handles two scenarios:
# 1. Prevents the "double update" problem when automatic reboots are disabled
# 2. Clears os_update metadata after the user has rebooted
#
# Double Update Problem:
# When a host has already downloaded an update but hasn't rebooted yet, it won't download
# a newer update until it reboots. This means users who delay rebooting will eventually
# reboot into an outdated version, then need to download and apply another update.
#
# This script periodically checks if the system is in UPDATE_STATUS_UPDATED_NEED_REBOOT
# state, and if so, resets the update status and checks for newer updates. This allows
# the system to download the newest version while waiting for the user to reboot.
#
# Metadata Cleanup:
# After the user reboots, the metadata still shows reboot_required=true. This script
# detects that the reboot has happened and clears the metadata.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

# Check current update status
STATUS_OUTPUT="$(update_engine_client -status 2>&1 || true)"
readonly STATUS_OUTPUT

echo "Current update engine status: ${STATUS_OUTPUT}"

# Check if we're in the UPDATE_STATUS_UPDATED_NEED_REBOOT state
if echo "${STATUS_OUTPUT}" | grep -q "UPDATE_STATUS_UPDATED_NEED_REBOOT"; then

  # Reset the update status to allow checking for newer updates
  update_engine_client -reset_status

  # Check for newer updates
  # Note: Using -check_for_update (not -update) as per Flatcar documentation
  update_engine_client -check_for_update

  echo "Reset complete. System will now download newer updates if available."
else

  # Check if metadata still indicates reboot is required
  # If so, the user must have rebooted, so clear the metadata
  echo "User has rebooted. Clearing os_update metadata..."

  set_metadata "os_update/reboot_required" ""
  set_metadata "os_update/timestamp" ""

  echo "Metadata cleared successfully"
fi

echo "check-for-newer-os-update.sh completed"
