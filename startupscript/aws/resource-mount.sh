#!/bin/bash

# resource-mount.sh
#
# Installs goofys for s3 bucket mounting. The script cannot yet mount s3 bucket automatically
# because workbench CLI requires aws user to manually login.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function)

if ! which goofys >/dev/null 2>&1; then

  emit "Installing goofys for s3 bucket mounting..."
  apt-get update
  apt-get install -y curl

  curl -L "https://github.com/kahing/goofys/releases/latest/download/goofys" -o goofys
  chmod +x goofys
  mv goofys /usr/local/bin/
else
  emit "goofys is already installed, skipping installation"
fi
