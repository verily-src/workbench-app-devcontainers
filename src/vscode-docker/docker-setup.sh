#!/usr/bin/with-contenv bash

# Get the GID of the Docker socket
if [ -S /var/run/docker.sock ]; then
    DOCKER_SOCK_GID=$(stat -c '%g' /var/run/docker.sock)
    echo "Docker socket found with GID: ${DOCKER_SOCK_GID}"

    # Create docker group with the correct GID if it doesn't exist
    if ! getent group ${DOCKER_SOCK_GID} > /dev/null 2>&1; then
        echo "Creating docker-host group with GID ${DOCKER_SOCK_GID}"
        groupadd -g ${DOCKER_SOCK_GID} docker-host
    else
        EXISTING_GROUP=$(getent group ${DOCKER_SOCK_GID} | cut -d: -f1)
        echo "Group with GID ${DOCKER_SOCK_GID} already exists: ${EXISTING_GROUP}"
    fi

    # Add abc user to the docker group
    GROUP_NAME=$(getent group ${DOCKER_SOCK_GID} | cut -d: -f1)
    if ! groups abc | grep -q "\b${GROUP_NAME}\b"; then
        echo "Adding abc user to ${GROUP_NAME} group"
        usermod -aG ${GROUP_NAME} abc
        echo "abc user groups: $(groups abc)"
    else
        echo "abc user is already in ${GROUP_NAME} group"
    fi
else
    echo "Warning: Docker socket not found at /var/run/docker.sock"
fi
