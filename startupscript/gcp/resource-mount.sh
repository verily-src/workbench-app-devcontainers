#!/bin/bash

# resource-mount.sh
#
# Installs gcsfuse if it is not already installed and mount resources.
#
# Both apt and install-from-source steps are based on gcloud docs here:
# https://cloud.google.com/storage/docs/gcsfuse-install
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and variables already being set:
#
# - emit (function)
# - Workbench CLI is installed

if ! which gcsfuse >/dev/null 2>&1; then
  if type apk > /dev/null 2>&1; then
    emit "Installing gcsfuse from source..."

    apk add --no-cache fuse git go

    export GOROOT=/usr/lib/go
    export GOPATH=/go
    mkdir -p ${GOPATH}/src ${GOPATH}/bin

    go install github.com/googlecloudplatform/gcsfuse/v2@master
    cp ${GOPATH}/bin/gcsfuse /usr/bin/gcsfuse

  elif type apt-get > /dev/null 2>&1; then
    emit "Installing gcsfuse from apt package..."

    # install packages needed to install gcsfuse
    apt-get install -y \
      fuse \
      lsb-release

    GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)"
    readonly GCSFUSE_REPO

    echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" > /etc/apt/sources.list.d/gcsfuse.list
    curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
    apt-get update \
      && apt-get install -y gcsfuse
  fi
else
  emit "gcsfuse already installed. Skipping installation."
fi

# Uncomment user_allow_other in the fuse.conf to enable non-root user to mount files with -o allow-other option.
sed -i '/user_allow_other/s/^#//g' /etc/fuse.conf

if [[ "${LOG_IN}" == "true" ]]; then
  ${RUN_AS_LOGIN_USER} "wb resource mount --allow-other || echo 'Resource mounting failed.'"
fi
