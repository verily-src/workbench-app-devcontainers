#!/bin/bash

# resource-mount.sh
#
# Installs goofys for s3 bucket mounting. The script cannot yet mount s3 bucket automatically
# because workbench CLI requires aws user to manually login.
#
# Note that this script is intended to be source from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up and some packages already installed:
#
# - emit (function)

emit "Installing goofys for s3 bucket mounting..."
apt-get update
apt-get install -y curl

curl -L "https://github.com/kahing/goofys/releases/download/v0.24.0/goofys" -o goofys
chmod +x goofys
mv goofys /usr/local/bin/
