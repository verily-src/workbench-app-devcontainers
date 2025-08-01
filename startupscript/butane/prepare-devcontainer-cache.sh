#!/bin/bash

# prepare-devcontainer-cache.sh prepares the devcontainer to be saved as a disk
# image.

set -o errexit
set -o nounset
set -o pipefail

export PATH="/opt/bin:$PATH"

function usage {
  echo "Usage: $0 [-d path] [image...]"
  echo "  -d path: optionally provide a path to a docker-compose directory to build."
  echo "  image: optionally provide additional docker images to cache."
}

while getopts ":hd:" opt; do
  case "$opt" in
    h )
      usage
      exit 0
      ;;
    d )
      DOCKER_DIR="$OPTARG"
      readonly DOCKER_DIR
      ;;
    \? )
      echo "Invalid option: -$OPTARG" >&2
      usage
      exit 1
      ;;
    : )
      echo "Option -$OPTARG requires an argument." >&2
      usage
      exit 1
      ;;
  esac
done

shift $((OPTIND - 1))

if [[ -n "${DOCKER_DIR+x}" ]] && [[ ! -d "${DOCKER_DIR}" ]]; then
  echo "Error: path '${DOCKER_DIR}' does not exist." >&2
  exit 1
fi

set -o xtrace

# Pull any requested images
for image in "$@"; do
  docker image pull "${image}"
done

if [[ -n "${DOCKER_DIR+x}" ]]; then
    # Build all sidecars
    pushd "${DOCKER_DIR}"
    while IFS='' read -r service; do
        docker-compose build "${service}"
    done < <(docker-compose config --services | sed '/^app$/d')
    popd
fi

# Stop docker and prevent it from starting again
systemctl mask docker
systemctl stop docker

# Remove any extraneous files. We only need to keep the images and the overlay2
# directories for the image content, as well as buildkit and engine-id for
# caching docker build layers (e.g. for devcontainer features).
find /var/lib/docker \
    -mindepth 1 -maxdepth 1 \
    ! -name image \
    ! -name overlay2 \
    ! -name buildkit \
    ! -name engine-id \
    -exec rm -rf {} +

# shellcheck source=/dev/null
source '/home/core/metadata-utils.sh'
set_metadata 'startup_script/status' "COMPLETED"

# Shut down the instance to signal that the image is ready to be saved.
systemctl poweroff
