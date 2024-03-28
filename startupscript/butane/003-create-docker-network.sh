#!/bin/bash
# create-docker-network.sh creates a docker network app-network if it does not exist.
# This script requires docker to be running on the VM.
set -e

readonly NETWORK_NAME="app-network"
if ! docker network inspect "${NETWORK_NAME}" &> /dev/null; then
    docker network create --driver bridge "${NETWORK_NAME}"
    echo "Created network: ${NETWORK_NAME}"
else
    echo "Network already exists: ${NETWORK_NAME}"
fi
