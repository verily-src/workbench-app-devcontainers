#!/bin/bash

# install-mountpoint-s3.sh
#
# Installs mountpoint-s3 for s3 bucket mounting.
#
# Note that this script is intended to be sourced from other scripts
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function): for logging output messages

readonly MOUNTPOINT_S3_VERSION="1.19.0"
readonly MOUNTPOINT_S3_KEY_FINGERPRINT="673FE4061506BB469A0EF857BE397A52B086DA5A"

# Exit early if already installed
if command -v mount-s3 >/dev/null 2>&1; then
  emit "mountpoint-s3 is already installed, skipping installation"
  return 0 2>/dev/null
fi

emit "Installing mountpoint-s3 v${MOUNTPOINT_S3_VERSION} for s3 bucket mounting..."

# Ensure gpg is available for signature verification
if type apk > /dev/null 2>&1; then
  apk update
  apk add --no-cache curl gnupg
elif type apt-get > /dev/null 2>&1; then
  apt-get update
  apt-get install -y curl gnupg
fi

# Download mountpoint-s3 and its signature (assuming x86_64)
readonly MP_URL="https://s3.amazonaws.com/mountpoint-s3-release/${MOUNTPOINT_S3_VERSION}/x86_64/mount-s3-${MOUNTPOINT_S3_VERSION}-x86_64.tar.gz"
readonly MP_SIG_URL="https://s3.amazonaws.com/mountpoint-s3-release/${MOUNTPOINT_S3_VERSION}/x86_64/mount-s3-${MOUNTPOINT_S3_VERSION}-x86_64.tar.gz.asc"

curl -L "${MP_URL}" -o mount-s3.tar.gz
curl -L "${MP_SIG_URL}" -o mount-s3.tar.gz.asc

# Import AWS public key for mountpoint-s3
emit "Importing AWS public key for mountpoint-s3 verification..."
# Download and import the official AWS public key for mountpoint-s3
curl -L "https://s3.amazonaws.com/mountpoint-s3-release/public_keys/KEYS" -o mountpoint-s3-keys.asc
gpg --import mountpoint-s3-keys.asc
rm mountpoint-s3-keys.asc

# Verify the fingerprint matches the expected value
GPG_OUTPUT=$(gpg --fingerprint mountpoint-s3@amazon.com)
FINGERPRINT_LINE=$(echo "${GPG_OUTPUT}" | grep -E "^\s*[0-9A-F]{4}\s[0-9A-F]{4}")
NO_SPACES=$(echo "${FINGERPRINT_LINE}" | tr -d ' ')
ACTUAL_FINGERPRINT=$(echo "${NO_SPACES}" | tr -d '\n')
readonly GPG_OUTPUT FINGERPRINT_LINE NO_SPACES ACTUAL_FINGERPRINT

if [[ "${ACTUAL_FINGERPRINT}" != *"${MOUNTPOINT_S3_KEY_FINGERPRINT}"* ]]; then
  emit "ERROR: mountpoint-s3 GPG key fingerprint verification failed!"
  emit "Expected fingerprint to contain: ${MOUNTPOINT_S3_KEY_FINGERPRINT}"
  gpg --fingerprint mountpoint-s3@amazon.com
  exit 1
fi

emit "mountpoint-s3 GPG key fingerprint verification successful"

# Verify GPG signature
if ! gpg --verify mount-s3.tar.gz.asc mount-s3.tar.gz; then
  emit "ERROR: mountpoint-s3 GPG signature verification failed!"
  rm -f mount-s3.tar.gz mount-s3.tar.gz.asc
  exit 1
fi

emit "mountpoint-s3 GPG signature verification successful"

# Extract the binary
TEMP_DIR=$(mktemp -d)
readonly TEMP_DIR
tar -xzf mount-s3.tar.gz -C "${TEMP_DIR}"

# Find the binary in the extracted files
if [[ -f "${TEMP_DIR}/bin/mount-s3" ]]; then
  chmod +x "${TEMP_DIR}/bin/mount-s3"
  mv "${TEMP_DIR}/bin/mount-s3" /usr/local/bin/
  emit "mountpoint-s3 installation successful"
else
  emit "ERROR: mount-s3 binary not found in extracted archive"
  exit 1
fi

# Clean up
rm -rf mount-s3.tar.gz mount-s3.tar.gz.asc "${TEMP_DIR}"
