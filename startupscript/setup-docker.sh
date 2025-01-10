#!/bin/bash
# setup-docker.sh
# Installs the docker CLI and configure the host machine's docker group to
# include the app container user.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

######################
# Install Docker CLI #
######################

sudo mkdir -p /etc/apt/keyrings && \
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null && \

sudo apt-get update && \
sudo apt-get install -y docker-ce-cli && \

###########################################
# Add container user to host docker group #
###########################################

# Add jupyter user to the host's docker group
sudo sed "/^docker:/ s/$/,jupyter/" /etc/host-group > /tmp/host-group.modified
sudo tee /etc/host-group < /tmp/host-group.modified > /dev/null

# create a matching docker group in the container and add the user to it
DOCKER_GID=$(grep '^docker:' "/etc/host-group" | cut -d: -f3)
if ! getent group docker; then
    groupadd -g $DOCKER_GID docker
fi
usermod -aG docker jupyter

###########################
# Configuring docker auth #
###########################

# Give user write permissions to the mounted docker config directory
sudo chown -R jupyter /home/jupyter/.docker

# Configure docker auth to use gcloud CLI for gcr.io
sudo -u jupyter bash -c 'gcloud auth configure-docker --quiet'
