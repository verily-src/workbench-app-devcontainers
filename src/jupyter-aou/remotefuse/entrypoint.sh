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

process_key() {
    if [ ! -f /ssh-keys/remotefuse.pub ]; then
        return
    fi

    # Add the app service's public key to authorized_keys in restricted mode
    (echo -n 'restrict '; cat /ssh-keys/remotefuse.pub) > "$SSH_DIR/authorized_keys"
    # Immediately remove the public key from the volume, so that we won't
    # try to reuse it. The main application container will generate a new
    # one.
    rm -f /ssh-keys/remotefuse.pub
}

readonly SSH_DIR="/home/remotefuse/.ssh"

# SSH Key setup
mkdir -p "$SSH_DIR"
touch "$SSH_DIR/authorized_keys"
chown -R remotefuse:users "$SSH_DIR"
chmod 600 "$SSH_DIR/authorized_keys"

process_key

service ssh start

inotifywait -m -e create -e moved_to /ssh-keys |
    while read -r; do
        process_key
    done
