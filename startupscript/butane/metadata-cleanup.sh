#!/bin/bash

# metadata-cleanup.sh cleans up the metadata set on the VM by the startup script and user access prober.
# This script is run on the host VM by a systemd timer unit to clean up the metadata on VM shutdown.
# UI relies on the metadata to show status of the VM so it's important to clear them on VM shutdown so that
# the UI don't show stale information on VM reboot.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

set_metadata "notebooks/last_activity" ""
set_metadata "startup_script/status" ""

