#!/bin/bash

set -o errexit
set -o nounset
set -o xtrace

cleanup() {
    find /home/remotefuse/workspace/ -mindepth 1 -maxdepth 1 -type d -exec fusermount -u {} \;
    find /home/remotefuse/workspace/ -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} \;
    exit
}
trap cleanup INT TERM

# SSH Key setup
mkdir -p /home/remotefuse/.ssh

if [ ! -f /ssh-keys/wb-key.pub ]; then
    printf "Waiting for ssh key..."
    until [ -f /ssh-keys/wb-key.pub ]; do
        sleep 3
        printf "."
    done
    printf "\n"
fi

# Add the app service's public key to authorized_keys in restricted mode
cd /home/remotefuse/.ssh || exit 1
(echo -n 'restrict '; cat /ssh-keys/wb-key.pub) >> ./authorized_keys
# Immediately remove the public key from the volume, so that we won't wrongly
# reuse it on the next startup. The main application container will generate a
# new one.
rm /ssh-keys/wb-key.pub
chmod 600 ./authorized_keys
chown -R remotefuse:users /home/remotefuse/.ssh

service ssh start

# Keep the container running, but in the background so that interrupts can be
# caught
tail -f /dev/null &
wait $!
