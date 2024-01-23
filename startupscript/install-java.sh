#!/bin/bash

# install-java.sh
#
# Creates a soft link in /usr/bin to the java runtime.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some variables and packages already being set up:
# 
# - java packages already installed in the container image or as 
# a devcontainer feature (ghcr.io/devcontainers/features/java:1).

# Check if the user name is provided.
if [[ -z "$1" ]]; then
    echo "usage: install-java.sh <user>."
    exit 1
fi
readonly user="${1}"
ln -sf "$(which java)" "/usr/bin"
chown --no-dereference "${user}" "/usr/bin/java"

