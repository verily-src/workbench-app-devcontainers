#!/bin/bash

# attach-docker-cache.sh scans for any newly attached docker cache disks and
# mounts them and integrates them with the docker root directory. This should
# run on system boot, before docker is started.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function attach {
  # Increase the levels of indirection for xtrace
  PS4="++ "
  set -o errexit
  set -o nounset
  set -o pipefail
  set -o xtrace

  local DISK_NAME="${1}"
  local DISK_UUID
  DISK_UUID="$(blkid -o value -s UUID "${DISK_NAME}")"
  local MOUNTPOINT="/dc/${DISK_UUID}"
  local DOCKER_ROOT="/var/lib/docker"

  if findmnt "${DISK_NAME}" > /dev/null; then
    echo "${DISK_NAME} is already mounted"
    return
  fi

  # Mount the read-only cache to a directory by its UUID, so that it will be
  # mounted at the same point across reboots
  mkdir -p "${MOUNTPOINT}"
  mount -o ro "${DISK_NAME}" "${MOUNTPOINT}"

  # Copy the overlay2 directories to the docker cache
  # shellcheck disable=SC2016
  find_args=(
    "${MOUNTPOINT}/overlay2" -maxdepth 1 -mindepth 1 -type d

    # Skip the "l" directory for now, since it contains relative symlinks that
    # we will copy directly in the next step
    ! -name "l"

    # If the directory already exists, skip the remaining steps. Pass the file
    # name as a shell parameter to avoid malicious injection.
    -execdir bash -c '[ ! -d "${1}" ] || (echo "Skipping existing directory ${1}"; exit 1)' shell "${DOCKER_ROOT}/overlay2/{}" \;

    # Copy the layer's metadata, preserving all file permissions. diff will be
    # handled in the next step, while work and merged are temporary
    # directories that we do not want to include
    -execdir rsync -a --exclude="diff" --exclude "work" --exclude "merged" "{}" /var/lib/docker/overlay2/ \;

    # The diff directory contains the actual data. Since overlayfs is able to
    # understand symlinks, we can just symlink the diff directory to the read-only
    # cache. We cannot simply symlink the entire directory, since docker needs
    # to create read-write work and merged directories to merge the layers
    -execdir ln -s "${MOUNTPOINT}/overlay2/{}/diff" "${DOCKER_ROOT}/overlay2/{}/diff" \;
  )
  find "${find_args[@]}"

  # Copy the links, ignoring existing files. These are relative symlinks, of the
  # format <short_id> -> ../<long_layer_id>
  rsync --ignore-existing -a "${MOUNTPOINT}/overlay2/l/" "${DOCKER_ROOT}/overlay2/l"

  # Copy the required image directories, ignoring existing files
  rsync --ignore-existing -a "${MOUNTPOINT}/image/overlay2/distribution/diffid-by-digest/sha256/" "${DOCKER_ROOT}/image/overlay2/distribution/diffid-by-digest/sha256"
  rsync --ignore-existing -a "${MOUNTPOINT}/image/overlay2/layerdb/sha256/" "${DOCKER_ROOT}/image/overlay2/layerdb/sha256"
}
readonly -f attach
export -f attach

# Set up the required docker directories if they don't exist
chmod 710 /var/lib/docker
# overlay2 contains the layer data
mkdir -p /var/lib/docker/overlay2
chmod 710 /var/lib/docker/overlay2
# image/overlay2/distribution/diffid-by-digest/sha256 maps the image digest to
# the diff hash
mkdir -p /var/lib/docker/image/overlay2/distribution/diffid-by-digest/sha256
# image/overlay2/layerdb/sha256 contains the image metadata, including the layer
# ID, parent image, and size of the layer
mkdir -p /var/lib/docker/image/overlay2/layerdb/sha256
chmod 700 -R /var/lib/docker/image

# Look for disk cache partitions, with priority to vwb caches. The attach
# function ignores anything that already exists, so by attaching the first-party
# VWB caches first, we can establish the priority:
#   1. local files
#   2. VWB caches
#   3. user-supplied caches
# shellcheck disable=SC2016
find /dev/disk/by-id/ -maxdepth 1 -name "scsi-0Google_PersistentDisk_vwb-docker-cache-*-part*" -exec bash -c 'attach "${1}"' shell "{}" \;
# shellcheck disable=SC2016
find /dev/disk/by-id/ -maxdepth 1 -name "scsi-0Google_PersistentDisk_docker-cache-*-part*" -exec bash -c 'attach "${1}"' shell "{}" \;
