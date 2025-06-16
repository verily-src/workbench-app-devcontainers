#!/bin/bash

# This script is a custom startup script for jupyter aou. It is used to generate
# an SSH key pair for the jupyter user to be used in the remotefuse sidecar.
# /ssh-keys should be a volume mounted to both containers. It also sets
# permissions on /home/jupyter/workspace to allow the jupyter user to read/write to
# it.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly USER_NAME="jupyter"
readonly RUN_AS_LOGIN_USER="sudo -u ${USER_NAME} bash -l -c"

rm -rf "/home/${USER_NAME}/.ssh"
${RUN_AS_LOGIN_USER} "mkdir -p '/home/${USER_NAME}/.ssh'"
${RUN_AS_LOGIN_USER} "ssh-keygen -q -f '/home/${USER_NAME}/.ssh/remotefuse' -N ''"
cp "/home/${USER_NAME}/.ssh/remotefuse.pub" /ssh-keys/remotefuse.pub

set +o errexit

chown -R ${USER_NAME}:users "/home/${USER_NAME}/workspace"

# Modify the startup script so that /opt/remotefuse always takes priority over
# /usr/bin
sed -i 's/export PATH=\/usr\/bin:/export PATH=\/opt\/remotefuse:\/usr\/bin:/g' /workspace/startupscript/post-startup.sh || true

sed -i '/^# If not running interactively/,/esac/d' "/home/${USER_NAME}/.bashrc"
