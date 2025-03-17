#!/bin/bash

# prepare-devcontainer-cache.sh prepares the devcontainer to be saved as a disk
# image.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function usage {
  echo "Usage: $0 <additonal_images>"
  echo "  additional_images: additional docker images to cache."
  exit 1
}

if [[ "$1" == "-h" || "$1" == "--help" || "$1" == "help" ]]; then
  usage
fi

# Pull any requested images
for image in "$@"; do
  docker image pull "${image}"
done

# Stop docker and prevent it from starting again
systemctl mask docker
systemctl stop docker

# Remove any extraneous files. We only need to keep the images and the overlay2
# directories.
find /var/lib/docker \
    ! -name image \
    ! -name overlay2 \
    -mindepth 1 -maxdepth 1 \
    -exec rm -rf {} +

# shellcheck source=/dev/null
source '/home/core/metadata-utils.sh'
set_metadata 'startup_script/status' "COMPLETED"

# Shut down the instance to signal that the image is ready to be saved.
systemctl poweroff
