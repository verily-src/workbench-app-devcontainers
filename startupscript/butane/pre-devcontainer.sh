#!/bin/bash

# pre-devcontainer.sh creates a file used by the devcontainer service to keep
# track of the number of service failures.

touch /tmp/devcontainer-failure-count