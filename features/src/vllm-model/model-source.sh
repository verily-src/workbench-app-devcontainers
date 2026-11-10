#!/bin/bash

# Prints the gs:// URL of a directory that lives on a gcsfuse bucket mount, or
# nothing if it is on local storage.
#
# Usage: model-source.sh <directory>
#
# start-vllm.sh uses it to tell a bucket-mounted model store from a local one:
# vLLM's default loader reads a mount badly (about 15 MB/s on an A100 VM, slower
# than local disk) while sequential reads of the same files run at 165 MB/s,
# so the store is prefetched into the page cache first. PROC_MOUNTS is for tests.

set -o errexit
set -o nounset
set -o pipefail

readonly DIR="${1:?Usage: model-source.sh <directory>}"
readonly MOUNTS="${PROC_MOUNTS:-/proc/mounts}"

if [[ "${DIR}" != /* ]]; then
  echo "model-source.sh: ${DIR} is not an absolute path" >&2
  exit 1
fi

# Longest gcsfuse mount point that contains the directory. Fields in /proc/mounts
# are octal-escaped; bucket names and Workbench mount points never need escaping.
best_point=""
best_bucket=""
while read -r source point fstype _; do
  [[ "${fstype}" == "fuse.gcsfuse" ]] || continue
  if [[ "${DIR}" == "${point}" || "${DIR}" == "${point}"/* ]] && (( ${#point} > ${#best_point} )); then
    best_point="${point}"
    best_bucket="${source}"
  fi
done < "${MOUNTS}"

if [[ -z "${best_point}" ]]; then
  exit 0
fi
relative="${DIR#"${best_point}"}"
relative="${relative#/}"
printf 'gs://%s%s\n' "${best_bucket}" "${relative:+/${relative}}"
