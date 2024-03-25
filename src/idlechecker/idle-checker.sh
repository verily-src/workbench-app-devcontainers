#!/bin/bash

# idle-checker.sh checks for cpu utilization of the VM and update last active timestamp if the CPU utilization
# is above a given threshold.
#
# Note that this script is dependent on some variables and packages being set up:
#
# - AWS CLI is installed
# - CLOUD: cloud platform VM is running on
# - bc https://manpages.ubuntu.com/manpages/trusty/en/man1/bc.1.html

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# threshold - threshold for cpu usage, used to determine if instance is idle. If usage goes above this number count resets to zero. By default 0.1 (10 percent)
readonly threshold="${THRESHOLD:-0.1}"
readonly LAST_ACTIVE_KEY="cpu-utilization/last-active"

function set_guest_attributes() {
  echo "Setting cpu-utilization/last-active"
  curl -s -X PUT --data "$1" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${LAST_ACTIVE_KEY}"
}
readonly -f set_guest_attributes

function create_tag() {
  echo "Creating tag vwbapp:cpu-utilization/last-active"
  INSTANCE_ID="$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)"
  aws ec2 create-tags \
    --resources "${INSTANCE_ID}" \
    --tags Key=vwbapp:${LAST_ACTIVE_KEY},Value="$1"
}
readonly -f create_tag

function set_cpu_last_active() {
  now=$(date +'%s')
  if [[ "${CLOUD}" == "gcp" ]]; then
    set_guest_attributes "${now}"
  else
    create_tag "${now}"
  fi  
}
readonly -f set_cpu_last_active

while true
do

  load=$(uptime | sed -e 's/.*load average: //g' | awk '{ print $1 }') # 1-minute average load
  load="${load//,}" # remove trailing comma
  echo "cpu load is $load"
  if (( $(echo "$threshold > $load" |bc -l) )); then
    echo "Idling.."
  else
    set_cpu_last_active
  fi

  sleep 60

done
