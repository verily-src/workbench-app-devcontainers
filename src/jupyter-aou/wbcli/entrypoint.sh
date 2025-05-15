#!/bin/bash

cleanup() {
    wb resource unmount
    exit
}
trap cleanup INT TERM

# SSH Key setup
mkdir -p /home/wbcli/.ssh
cd /home/wbcli/.ssh

# Generate a new ssh key and add it to authorized_keys
ssh-keygen -q -f ./wb-key -N ""
(echo -n 'restrict '; cat ./wb-key.pub) >> ./authorized_keys
chmod 600 ./authorized_keys
chown -R wbcli:wbcli /home/wbcli/.ssh
service ssh start

# SSH permission checking is only run when ssh is run by the owner of the key
# file. Set the owner to nobody, but allow universal read access
mv ./wb-key /ssh-keys/wb-key
chmod 644 /ssh-keys/wb-key
chown nobody /ssh-keys/wb-key

chmod a+w /home/wbcli/workspace

# Install CLI and mount resources
# TODO takes too long to set up, set up in docker container
/workspace/startupscript/post-startup.sh wbcli /home/wbcli $CLOUD $LOG_IN

touch /ready

# Keep the container running, but in the background so that interrupts can be
# caught
tail -f /dev/null &
wait $!
