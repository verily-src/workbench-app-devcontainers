#!/bin/bash

# wb.sh - Workbench Docker Wrapper
#
# This script is a thin wrapper around `docker run` that provides:
# - Host networking to allow access to cloud instance metadata
# - Volume mounting for data persistence (/workbench_context)
# - Argument passing to the wb command inside the container
#
# The script sources configuration from values.sh which should define:
# - WB_CONTEXT_DIR: Local directory to mount for persistence
# - WB_IMAGE_NAME: Docker image name to run
#
# Usage: ./wb.sh [arguments...]
# All arguments are passed through to the container.

set -o errexit
set -o nounset
set -o pipefail

# Source configuration variables
source '/home/core/wb/values.sh'

# Run the workbench container with:
# - Host networking (--network host)
# - Volume mount for persistence (-v)
# - Pass all script arguments to container ("${@}")
docker run \
    --network host \
    -v "${WB_CONTEXT_DIR}:/workbench_context:rw" \
    "${WB_IMAGE_NAME}" "${@}"
