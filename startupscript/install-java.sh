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
# - USER_NAME: app user name
# - USER_PRIMARY_GROUP: name of primary group app user belongs to

# Check if the user name is provided.
ln -sf "$(which java)" "/usr/bin"
chown --no-dereference "${USER_NAME}:${USER_PRIMARY_GROUP}" "/usr/bin/java"

