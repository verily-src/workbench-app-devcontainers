#!/bin/bash

# idle-checker.sh checks for CPU utilization of the VM and updates last active timestamp if the CPU utilization
# is above a given threshold.
#
# Note that this script is dependent on some environment variables and packages being set up:
#
# Environment variables:
# - CLOUD: cloud platform VM is running on
#
# Software:
# - AWS CLI

# - CLOUD: cloud platform VM is running on

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# threshold - threshold for cpu usage, used to determine if instance is idle. If usage goes above this number count resets to zero. By default 0.1 (10 percent)
readonly THRESHOLD="${THRESHOLD:-0.1}"
readonly LAST_ACTIVE_KEY="last-active/cpu"

function emit() {
 echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

function set_guest_attributes() {
  emit "Setting cpu-utilization/last-active"
  curl -s -X PUT --data "$1" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${LAST_ACTIVE_KEY}"
}
readonly -f set_guest_attributes

function create_tag() {
  emit "Creating tag vwbapp:cpu-utilization/last-active"
  local id
  id="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  aws ec2 create-tags \
    --resources "${id}" \
    --tags Key=vwbapp:${LAST_ACTIVE_KEY},Value="$1"
}
readonly -f create_tag

function set_cpu_last_active() {
  local now
  now=$(date +'%s')
  if [[ "${CLOUD}" == "gcp" ]]; then
    set_guest_attributes "${now}"
  elif [[ "${CLOUD}" == "aws" ]]; then
    create_tag "${now}"
  else
    1>&2 emit "Unexpected cloud platform ${CLOUD}"  
    exit 1
  fi  
}
readonly -f set_cpu_last_active

declare LOAD
while true; do
  LOAD="$(awk '{print $1}' /proc/loadavg)" # 1-minute average load
  emit "cpu load is ${LOAD}"
  # Check if the LOAD has exceeded the THRESHOLD.  
  # Note the use of awk for comparison of real numbers.  
  if echo "${THRESHOLD}" "${LOAD}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    emit "Idling.."
  else
    set_cpu_last_active
  fi
  sleep 60
done
