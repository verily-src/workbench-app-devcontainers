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

echo "=== RESOURCE-MOUNT.SH (GCP) STARTING ===" >&2

echo "  [resource-mount] Checking for gcsfuse..." >&2
if ! which gcsfuse >/dev/null 2>&1; then
  echo "  [resource-mount] gcsfuse not found, installing..." >&2
  if type apk > /dev/null 2>&1; then
    emit "Installing gcsfuse from source..."
    echo "  [resource-mount] Using apk package manager" >&2

    apk add --no-cache fuse git go

    export GOROOT=/usr/lib/go
    export GOPATH=/go
    mkdir -p ${GOPATH}/src ${GOPATH}/bin

    go install github.com/googlecloudplatform/gcsfuse/v2@master
    cp ${GOPATH}/bin/gcsfuse /usr/bin/gcsfuse
    echo "  [resource-mount] gcsfuse installed from source successfully" >&2

  elif type apt-get > /dev/null 2>&1; then
    emit "Installing gcsfuse from apt package..."
    echo "  [resource-mount] Using apt package manager" >&2

    # install packages needed to install gcsfuse
    apt-get install -y \
      fuse \
      lsb-release

    GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)"
    readonly GCSFUSE_REPO
    echo "  [resource-mount] GCSFUSE_REPO=${GCSFUSE_REPO}" >&2

    echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" > /etc/apt/sources.list.d/gcsfuse.list
    curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
    apt-get update \
      && apt-get install -y gcsfuse
    echo "  [resource-mount] gcsfuse installed from apt successfully" >&2
  fi
else
  emit "gcsfuse already installed. Skipping installation."
  echo "  [resource-mount] gcsfuse found at: $(which gcsfuse)" >&2
fi

if [[ "${LOG_IN}" == "true" ]]; then
  echo "  [resource-mount] LOG_IN=true, attempting to mount resources..." >&2
  echo "  [resource-mount] Running: ${RUN_AS_LOGIN_USER} '${WORKBENCH_INSTALL_PATH}' resource mount --allow-other" >&2
  ${RUN_AS_LOGIN_USER} "'${WORKBENCH_INSTALL_PATH}' resource mount --allow-other || echo 'Resource mounting failed.'"
  echo "  [resource-mount] Resource mount command completed" >&2
else
  echo "  [resource-mount] LOG_IN=${LOG_IN}, skipping resource mounting" >&2
fi

echo "=== RESOURCE-MOUNT.SH (GCP) COMPLETE ===" >&2
