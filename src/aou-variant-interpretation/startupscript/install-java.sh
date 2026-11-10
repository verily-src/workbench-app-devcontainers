#!/bin/bash

# install-java.sh
#
# Creates a soft link in /usr/bin to the java runtime.
#
# Note that this script is intended to be sourced from the "post-startup.sh" script
# and is dependent on some variables and packages already being set up:
# 
# - java already installed in the container image (deploy/Dockerfile's
#   eclipse-temurin base; there is deliberately no devcontainer java feature).
# - USER_NAME: app user name
# - USER_PRIMARY_GROUP: name of primary group app user belongs to

# Check if the user name is provided.
if [ ! -f "/usr/bin/java" ]; then
  ln -sf "$(which java)" "/usr/bin"
  chown --no-dereference "${USER_NAME}:${USER_PRIMARY_GROUP}" "/usr/bin/java"
fi

