#!/bin/bash

# values.sh - Workbench Container Configuration Constants
#
# This file defines the configuration constants used when setting up and running
# the wb (workbench) container in GCP environments. These values are sourced by
# other scripts to ensure consistent configuration across the workbench deployment.
#
# Constants defined:
# - WB_ROOT: Base directory for workbench files and configuration
# - WB_DOCKERFILE: Path to the Dockerfile used to build the wb container
# - WB_IMAGE_NAME: Docker image name/tag for the workbench container
# - WB_CONTEXT_DIR: Directory mounted into container for data persistence
# - WB_LOGIN_MODE: Authentication method for GCP services

# shellcheck disable=SC2034
readonly WB_ROOT="/home/core/wb"
readonly WB_DOCKERFILE="${WB_ROOT}/Dockerfile"
readonly WB_IMAGE_NAME="wb"
readonly WB_CONTEXT_DIR="${WB_ROOT}/context"
readonly WB_LOGIN_MODE="APP_DEFAULT_CREDENTIALS"
