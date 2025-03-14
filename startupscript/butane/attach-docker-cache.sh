#!/bin/bash

# attach-docker-cache.sh scans for any newly attached docker cache disks and
# mounts them and integrates them with the docker root directory.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

function attach {
  if findmnt "${1}" > /dev/null; then
    echo "${1} is already mounted"
    return
  fi

  id="$(uuidgen)"
  mkdir -p "/dc/${id}"

  mount "${1}" "/dc/${id}"


  cd "/dc/${id}/overlay2"

  # Copy the overlay2 directories to the docker cache, symlinking the diff
  # directories and excluding the work and merged directories. Skip directories
  # that already exist
  find . -maxdepth 1 -mindepth 1 -type d ! -name "l" \
      -exec bash -c '[ ! -d "/var/lib/docker/overlay2/{}" ] || (echo "Skipping existing directory {}"; exit 1)' \
      -exec rsync -a --exclude="diff" --exclude "work" --exclude "merged" "{}" /var/lib/docker/overlay2/ \; \
      -exec ln -s "/dc/${id}/overlay2/{}/diff" "/var/lib/docker/overlay2/{}/diff" \;

  # Copy the links, ignoring existing files
  rsync --ignore-existing -a ./l/ /var/lib/docker/overlay2/l

  cd "/dc/${id}/image/overlay2"

  # Copy the required image directories, ignoring existing files
  rsync --ignore-existing -a ./distribution/diffid-by-digest/sha256/ /var/lib/docker/image/overlay2/distribution/diffid-by-digest/sha256
  rsync --ignore-existing -a ./layerdb/sha256/ /var/lib/docker/image/overlay2/layerdb/sha256
}
readonly -f attach
export -f attach

# Set up the required docker directories if they don't exist
chmod 710 /var/lib/docker
mkdir -p /var/lib/docker/overlay2
chmod 710 /var/lib/docker/overlay2
mkdir -p /var/lib/docker/image/overlay2/distribution/diffid-by-digest/sha256
mkdir -p /var/lib/docker/image/overlay2/layerdb/sha256
chmod 700 -R /var/lib/docker/image

# Look for disk cache partitions, with priority to vwb caches
find /dev/disk/by-id/ -maxdepth 1 -name "scsi-0Google_PersistentDisk_vwb-docker-cache-*-part*" -exec bash -c 'attach "{}"' \;
find /dev/disk/by-id/ -maxdepth 1 -name "scsi-0Google_PersistentDisk_docker-cache-*-part*" -exec bash -c 'attach "{}"' \;
