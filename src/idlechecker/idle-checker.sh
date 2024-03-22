#!/bin/bash

# idle-checker.sh checks for cpu utilization of the VM and update last active timestamp if the CPU utilization
# is above a given threshold.

# threshold - threshold for cpu usage, used to determine if instance is idle. If usage goes above this number count resets to zero. By default 0.1 (10 percent)

readonly threshold="${THRESHOLD:-0.1}"

function set_cpu_last_active() {
  curl -s -X PUT --data "${attr_value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/cpu-utilization/last-active"
}
readonly -f set_cpu_last_active

while true
do

  load=$(uptime | sed -e 's/.*load average: //g' | awk '{ print $1 }') # 1-minute average load
  load="${load//,}" # remove trailing comma
  echo "cpu load is $load"
  res=$(echo $load'<'$threshold | bc -l)
  if (( $load < $threshold )); then
    echo "Idling.."
  else
    set_cpu_last_active $(date +'%s')
  fi

  sleep 60

done
