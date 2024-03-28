#!/bin/bash

# create-docker-network.sh creates a docker network app-network if it does not exist.
# devcontainer apps should be connected to this network instead of the default one.
# This script requires docker to be running on the VM.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly NETWORK_NAME="app-network"
if ! docker network inspect "${NETWORK_NAME}" &> /dev/null; then
    docker network create --driver bridge "${NETWORK_NAME}"
    echo "Created Docker network: ${NETWORK_NAME}"
else
    echo "Docker network already exists: ${NETWORK_NAME}"
fi
