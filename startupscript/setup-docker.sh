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

mkdir -p /etc/apt/keyrings && \
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \

apt-get update && \
apt-get install -y docker-ce-cli && \

###########################################
# Add container user to host docker group #
###########################################

# Add jupyter user to the host's docker group
sed "/^docker:/ s/$/,jupyter/" /etc/host-group > /tmp/host-group.modified
tee /etc/host-group < /tmp/host-group.modified > /dev/null

# create a matching docker group in the container and add the user to it
DOCKER_GID=$(grep '^docker:' "/etc/host-group" | cut -d: -f3)
if ! getent group docker; then
    groupadd -g "$DOCKER_GID" docker
fi
usermod -aG docker jupyter

###########################
# Configuring docker auth #
###########################

# Give user write permissions to the mounted docker config directory
chown -R jupyter /home/jupyter/.docker

# Login to docker with gcloud credentials (needs to be re-run every 30 min if needed)
sudo -u jupyter /bin/bash -c "docker login -u oauth2accesstoken -p $(gcloud auth print-access-token) https://us-central1-docker.pkg.dev"
