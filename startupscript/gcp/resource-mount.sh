#!/bin/bash

# resource-mount.sh
#
# Installs gcsfuse if it is not already installed and mount resources.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and variables already being set:
#
# - emit (function)
# - Workbench CLI is installed
 
if ! which gcsfuse >/dev/null 2>&1; then
  emit "Installing gcsfuse..."

  # install packages needed to install gcsfuse
  apt-get install -y \
    fuse \
    lsb-release

  # Install based on gcloud docs here https://cloud.google.com/storage/docs/gcsfuse-install.
  GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)"
  readonly GCSFUSE_REPO

  echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" > /etc/apt/sources.list.d/gcsfuse.list
  curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
  apt-get update \
    && apt-get install -y gcsfuse
else
  emit "gcsfuse already installed. Skipping installation."
fi

# Uncomment user_allow_other in the fuse.conf to enable non-root user to mount files with -o allow-other option.
sed -i '/user_allow_other/s/^#//g' /etc/fuse.conf

if [[ "${LOG_IN}" == "true" ]]; then
  ${RUN_AS_LOGIN_USER} "wb resource mount --allow-other"
fi
