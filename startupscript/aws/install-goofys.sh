#!/bin/bash

# install-goofys.sh
#
# Installs goofys for s3 bucket mounting.
#
# Note that this script is intended to be sourced from other scripts
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function): for logging output messages

# Version configuration
readonly GOOFYS_VERSION="v0.24.0"
readonly GOOFYS_SHA256="729688b6bc283653ea70f1b2b6406409ec1460065161c680f3b98b185d4bf364"

# Exit early if already installed
if command -v goofys >/dev/null 2>&1; then
  emit "goofys is already installed, skipping installation"
  return 0 2>/dev/null
fi

emit "Installing goofys ${GOOFYS_VERSION} for s3 bucket mounting..."
if type apk > /dev/null 2>&1; then
  apk update
  apk add --no-cache curl
elif type apt-get > /dev/null 2>&1; then
  apt-get update
  apt-get install -y curl
fi

# Download specific version
curl -L "https://storage.googleapis.com/bkt-workbench-artifacts/mirror/goofys-${GOOFYS_VERSION}" -o goofys

# Verify SHA256 hash
SHA256_OUTPUT=$(sha256sum goofys)
ACTUAL_SHA256=$(echo "${SHA256_OUTPUT}" | cut -d' ' -f1)
readonly SHA256_OUTPUT ACTUAL_SHA256

if [[ "${ACTUAL_SHA256}" != "${GOOFYS_SHA256}" ]]; then
  emit "ERROR: goofys SHA256 verification failed!"
  emit "Expected: ${GOOFYS_SHA256}"
  emit "Actual:   ${ACTUAL_SHA256}"
  rm goofys
  exit 1
fi

emit "goofys SHA256 verification successful"
chmod +x goofys
mv goofys /usr/local/bin/
