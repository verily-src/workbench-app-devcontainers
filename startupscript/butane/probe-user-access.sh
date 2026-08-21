#!/bin/bash

# probe-user-access.sh records the latest user activity on the VM as guest
# attributes, which idle-shutdown.sh reads to decide whether to stop the VM.
#
# Three independent signals are recorded, and idle-shutdown.sh takes the most
# recent of the three:
#   last-active/proxy - last request forwarded to the backend by the proxy agent
#   last-active/ssh   - an interactive ssh session is present
#   last-active/cpu   - CPU activity of the application container (see below)
#
# CPU ACTIVITY IS MEASURED PER CONTAINER, NOT PER VM.
# This script used to derive CPU activity from the whole-VM 15-minute load
# average (/proc/loadavg). That attributes CPU burned by sidecar containers to
# the user: any template that runs a continuously busy sidecar keeps the load
# average above the threshold forever, so last-active/cpu is refreshed on every
# probe, idle-shutdown.sh never fires, and the VM bills indefinitely even though
# nobody is using it. We therefore measure only the container that runs the
# user's workload.
#
# UNITS: the container CPU threshold is a percentage of ONE CPU core, computed
# from the container's cgroup CPU accounting. 100.0 means the container consumed
# one core continuously across the sample interval; the value can exceed 100.0
# on a multi-vCPU VM (a 4-vCPU VM tops out at 400.0). It is deliberately NOT
# normalized by core count, so the threshold means the same thing on every
# machine size. This is a different unit and a different scale from
# /proc/loadavg, so the default threshold is not the same number the
# load-average check used -- see DEFAULT_CPU_PERCENT_THRESHOLD below.
#
# usage: probe-user-access.sh [load-threshold] [container-cpu-percent-threshold]
#   $1 load-threshold (default 0.1). Unchanged meaning: a whole-VM 15-minute
#      load average. Now only consulted by the fallback path described below.
#   $2 container-cpu-percent-threshold (default 5.0), as a percentage of one
#      core. Below this the application container is considered idle.
#
# The container to measure defaults to "application-server" and can be
# overridden per VM with the "idle-cpu-container-name" instance attribute,
# for templates where the user's workload runs in a differently named container.
#
# If the container cannot be measured at all -- it does not exist yet, is not
# running, or exposes no cgroup CPU accounting -- the script falls back to the
# previous whole-VM load-average behaviour using $1. Falling back keeps the VM
# alive rather than risking a premature shutdown of a workspace we cannot
# measure.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Logs to stderr, not stdout: the helpers below return their values on stdout
# via command substitution, so log lines must not be captured with them.
function emit() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >&2
}
readonly -f emit

# Allow tests to point at a stub. Production always uses /home/core.
METADATA_UTILS="${METADATA_UTILS:-/home/core/metadata-utils.sh}"
readonly METADATA_UTILS
# shellcheck source=/dev/null
source "${METADATA_UTILS}"

readonly DEFAULT_LOAD_THRESHOLD="0.1"
# 5% of one core. An idle application server (ioloop heartbeats, autosave,
# health checks) sits well under 2% of a core, while genuine user work is
# far above 5%. For reference the old load-average threshold of 0.1 meant
# "one runnable task 10% of the time", i.e. roughly 10% of one core measured
# across the whole VM; now that sidecar and host noise is excluded we can
# afford to be more sensitive than that.
readonly DEFAULT_CPU_PERCENT_THRESHOLD="5.0"
readonly DEFAULT_APP_CONTAINER_NAME="application-server"
readonly APP_CONTAINER_METADATA_KEY="idle-cpu-container-name"

# CGROUP_ROOT, PROC_ROOT and STATE_DIR are overridable only so the unit tests
# can point at fixtures. Production always uses the real paths.
readonly CGROUP_ROOT="${CGROUP_ROOT:-/sys/fs/cgroup}"
readonly PROC_ROOT="${PROC_ROOT:-/proc}"
readonly STATE_DIR="${STATE_DIR:-/run/probe-user-access}"
readonly STATE_FILE="${STATE_DIR}/app-cpu-sample"
# Only used when there is no previous sample to diff against.
readonly FALLBACK_SAMPLE_SECONDS="${FALLBACK_SAMPLE_SECONDS:-3}"
# A gap shorter than this is too small to average over, so the previous
# sample is discarded and an in-place sample is taken instead.
readonly MIN_SAMPLE_NSEC=1000000000

LOAD_THRESHOLD="${1:-${DEFAULT_LOAD_THRESHOLD}}"
readonly LOAD_THRESHOLD
CPU_PERCENT_THRESHOLD="${2:-${DEFAULT_CPU_PERCENT_THRESHOLD}}"
readonly CPU_PERCENT_THRESHOLD

###############################################################################
# Proxy activity (unchanged)
###############################################################################

readonly PROXY_CONTAINER_NAME="proxy-agent"
if [[ "$(docker container inspect -f '{{.State.Running}}' "${PROXY_CONTAINER_NAME}")" == "true" ]]; then
    # Tolerates pipefail here when there's no matching log.
    # example logs: 2024/03/29 16:15:58 Forwarded request to backend
    LOG="$(docker logs "${PROXY_CONTAINER_NAME}" 2>&1 | grep 'Forwarded request to backend' | tail -1 || true)"
    if [[ -n "${LOG}" ]]; then
        TIMESTAMP=$(echo "${LOG}" | awk '{print $1 " " $2}')
        UNIX_TIME=$(date -d "${TIMESTAMP}" +"%s")
        set_metadata "last-active/proxy" "${UNIX_TIME}"
    fi
fi

###############################################################################
# Application container CPU activity
###############################################################################

# Echoes "<file> <unit>" for the cgroup CPU accounting of the given pid, where
# unit is "usec" (cgroup v2 cpu.stat) or "nsec" (cgroup v1 cpuacct.usage).
# Returns non-zero if no readable accounting file was found.
function find_cpu_acct_file() {
  local pid="$1"
  local proc_cgroup="${PROC_ROOT}/${pid}/cgroup"
  if [[ ! -r "${proc_cgroup}" ]]; then
    return 1
  fi

  local rel
  # cgroup v2 lists a single unified hierarchy as "0::<path>".
  rel="$(awk -F: '$1 == "0" && $2 == "" {print $3; exit}' "${proc_cgroup}")"
  if [[ -n "${rel}" && -r "${CGROUP_ROOT}${rel}/cpu.stat" ]]; then
    echo "${CGROUP_ROOT}${rel}/cpu.stat usec"
    return 0
  fi

  # cgroup v1 keeps a cumulative nanosecond counter under the cpuacct
  # controller, which may be mounted alone or co-mounted as "cpu,cpuacct".
  rel="$(awk -F: '$2 ~ /(^|,)cpuacct(,|$)/ {print $3; exit}' "${proc_cgroup}")"
  if [[ -n "${rel}" && -r "${CGROUP_ROOT}/cpuacct${rel}/cpuacct.usage" ]]; then
    echo "${CGROUP_ROOT}/cpuacct${rel}/cpuacct.usage nsec"
    return 0
  fi

  return 1
}
readonly -f find_cpu_acct_file

# Echoes the cumulative CPU time of the accounting file in microseconds.
function read_cpu_usage_usec() {
  local file="$1"
  local unit="$2"
  local raw

  if [[ "${unit}" == "usec" ]]; then
    raw="$(awk '$1 == "usage_usec" {print $2; found = 1} END {exit !found}' "${file}")" || return 1
  else
    raw="$(cat "${file}")" || return 1
  fi

  if [[ ! "${raw}" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  if [[ "${unit}" == "usec" ]]; then
    echo "${raw}"
  else
    echo "$(( raw / 1000 ))"
  fi
}
readonly -f read_cpu_usage_usec

# Echoes "<cpu_usec> <monotonic_nsec>" for the given pid.
function sample_cpu() {
  local file="$1"
  local unit="$2"
  local usage
  usage="$(read_cpu_usage_usec "${file}" "${unit}")" || return 1
  echo "${usage} $(date +%s%N)"
}
readonly -f sample_cpu

# Echoes the CPU usage of the named container as a percentage of one core.
# Returns non-zero if the container cannot be measured.
function measure_container_cpu_percent() {
  local container="$1"

  local inspected
  inspected="$(docker inspect --format '{{.Id}} {{.State.Pid}}' "${container}" 2>/dev/null)" || return 1
  local id pid
  read -r id pid <<<"${inspected}"
  # A stopped or never-started container reports pid 0.
  if [[ ! "${pid}" =~ ^[0-9]+$ ]] || (( pid == 0 )); then
    return 1
  fi

  local acct file unit
  acct="$(find_cpu_acct_file "${pid}")" || return 1
  read -r file unit <<<"${acct}"

  local usage_now stamp_now sample
  sample="$(sample_cpu "${file}" "${unit}")" || return 1
  read -r usage_now stamp_now <<<"${sample}"

  # Prefer diffing against the sample taken by the previous probe run: it
  # averages CPU over the whole inter-probe interval, which smooths out short
  # bursts, and it costs nothing. /run is a tmpfs so the state never survives a
  # reboot, and a container restart is caught by comparing the container id.
  local usage_before stamp_before prev_id prev_usage prev_stamp
  usage_before=""
  stamp_before=""
  if read -r prev_id prev_usage prev_stamp < "${STATE_FILE}" 2>/dev/null \
      && [[ "${prev_id}" == "${id}" ]] \
      && [[ "${prev_usage}" =~ ^[0-9]+$ && "${prev_stamp}" =~ ^[0-9]+$ ]] \
      && (( usage_now >= prev_usage )) \
      && (( stamp_now - prev_stamp >= MIN_SAMPLE_NSEC )); then
    usage_before="${prev_usage}"
    stamp_before="${prev_stamp}"
  fi

  if [[ -z "${usage_before}" ]]; then
    # First probe after boot, or the container just restarted, so there is no
    # usable baseline. Take a short sample in place rather than guessing.
    emit "No usable previous CPU sample for ${container}; sampling for ${FALLBACK_SAMPLE_SECONDS}s."
    usage_before="${usage_now}"
    stamp_before="${stamp_now}"
    sleep "${FALLBACK_SAMPLE_SECONDS}"
    sample="$(sample_cpu "${file}" "${unit}")" || return 1
    read -r usage_now stamp_now <<<"${sample}"
    if (( usage_now < usage_before || stamp_now <= stamp_before )); then
      return 1
    fi
  fi

  mkdir -p "${STATE_DIR}"
  echo "${id} ${usage_now} ${stamp_now}" > "${STATE_FILE}"

  # Percent of one core, i.e. cpu time used / wall time elapsed * 100. The
  # elapsed time is in nanoseconds and the used time in microseconds, so the
  # 1000x unit difference folds into the multiplier: 100 * 1000 = 100000.
  awk -v used="$(( usage_now - usage_before ))" \
      -v elapsed_nsec="$(( stamp_now - stamp_before ))" \
      'BEGIN { printf "%.2f", (used * 100000) / elapsed_nsec }'
}
readonly -f measure_container_cpu_percent

APP_CONTAINER_NAME="$(get_metadata_value "${APP_CONTAINER_METADATA_KEY}" "${DEFAULT_APP_CONTAINER_NAME}")"
if [[ -z "${APP_CONTAINER_NAME}" ]]; then
  APP_CONTAINER_NAME="${DEFAULT_APP_CONTAINER_NAME}"
fi
readonly APP_CONTAINER_NAME

CPU_IS_ACTIVE="false"
CPU_PERCENT="$(measure_container_cpu_percent "${APP_CONTAINER_NAME}" || true)"
readonly CPU_PERCENT
if [[ -n "${CPU_PERCENT}" ]]; then
  emit "Container ${APP_CONTAINER_NAME} CPU usage is ${CPU_PERCENT}% of one core (threshold ${CPU_PERCENT_THRESHOLD}%)."
  # Note the use of awk for comparison of real numbers.
  if echo "${CPU_PERCENT_THRESHOLD}" "${CPU_PERCENT}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    emit "Container ${APP_CONTAINER_NAME} is idle."
  else
    CPU_IS_ACTIVE="true"
  fi
else
  # Could not measure the container. Fall back to the previous whole-VM
  # load-average behaviour so an unmeasurable container cannot cause a
  # premature shutdown.
  LOAD="$(awk '{print $3}' "${PROC_ROOT}/loadavg")" # 15-minute average load
  emit "Could not measure CPU for container ${APP_CONTAINER_NAME}; falling back to whole-VM load average ${LOAD} (threshold ${LOAD_THRESHOLD})."
  if echo "${LOAD_THRESHOLD}" "${LOAD}" | awk '{if ($1 > $2) exit 0; else exit 1}'; then
    emit "Idling.."
  else
    CPU_IS_ACTIVE="true"
  fi
fi
readonly CPU_IS_ACTIVE

if [[ "${CPU_IS_ACTIVE}" == "true" ]]; then
  NOW="$(date +'%s')"
  set_metadata "last-active/cpu" "${NOW}"
fi

###############################################################################
# SSH activity (unchanged)
###############################################################################

if pgrep -af 'sshd-session.*@'; then
  echo "Detect an active ssh session"
  NOW="$(date +'%s')"
  set_metadata "last-active/ssh" "${NOW}"
fi
