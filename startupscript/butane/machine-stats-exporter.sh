#!/bin/bash
# machine-stats-exporter.sh
# Collects CPU, memory, and disk usage and prints a single JSON object
# to stdout. Run by a systemd timer so fluent-bit captures it from the journal.

set -o errexit
set -o nounset
set -o pipefail

# --- CPU ---
cpu_count=$(nproc)

# Load average (1m) normalized by CPU count--can exceed 1.0 under overload
# (e.g. waiting for I/O)
cpu_load=$(awk '{print $1}' /proc/loadavg)
cpu_load_normalized=$(awk "BEGIN {printf \"%.4f\", ${cpu_load}/${cpu_count}}")

# --- Memory ---
mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_available_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
mem_used_kb=$(( mem_total_kb - mem_available_kb ))
mem_total_bytes=$(( mem_total_kb * 1024 ))
mem_used_bytes=$(( mem_used_kb * 1024 ))
mem_usage_ratio=$(awk "BEGIN {printf \"%.4f\", ${mem_used_kb}/${mem_total_kb}}")

# --- Disk (for / and /var/lib/docker) ---
disk_json="[]"
while read -r source size used mount; do
  disk_json=$(echo "${disk_json}" | jq \
    --arg dev "${source}" \
    --arg mp "${mount}" \
    --argjson total "${size}" \
    --argjson used "${used}" \
    '. + [{device: $dev, mountpoint: $mp, total_bytes: $total, used_bytes: $used, usage_ratio: (($used / $total * 10000 | floor) / 10000)}]')
done < <(df -B1 --output=source,size,used,target / /var/lib/docker 2>/dev/null | tail -n +2)

# --- Docker container stats (CPU and memory usage ratios) ---
# CPUPerc and MemPerc are formated as percentages (e.g. "15%"), so we strip
# the '%' and convert to a ratio (e.g. 0.15), rounded to 4 decimal places to
# avoid floating point funkiness.
containers_json=$(
  # Get CPU/memory usage from docker stats (only running containers)
  # .ID is a 12-char short ID we use as the join key.
  stats=$(docker stats --no-stream --format '{{json .}}' 2>/dev/null \
    | jq -sc '[.[] | {
        id: .ID,
        cpu_usage_ratio: (.CPUPerc | rtrimstr("%") | tonumber * 100 | floor | . / 10000),
        memory_usage_ratio: (.MemPerc | rtrimstr("%") | tonumber * 100 | floor | . / 10000)
      }]') || stats="[]"

  # Get state from docker inspect for all containers.
  # .Id is the full 64-char ID; truncate to 12 to match docker stats.
  state=$(docker ps -aq | xargs docker inspect 2>/dev/null \
    | jq -c '[.[] | {
        id: .Id[:12],
        name: .Name,
        state: .State | {
          status: .Status,
          running: .Running,
          paused: .Paused,
          restarting: .Restarting,
          oom_killed: .OOMKilled,
          dead: .Dead,
          exit_code: .ExitCode,
          error: .Error,
          started_at: .StartedAt,
          finished_at: (.FinishedAt | if . == "0001-01-01T00:00:00Z" then null else . end)
        }}]') || state="[]"

  # Merge stats into state by container ID
  jq -nc --argjson stats "$stats" --argjson state "$state" '
    ($stats | map({(.id): .}) | add // {}) as $s |
    [$state[] | . + ($s[.id] // {cpu_usage_ratio: 0, memory_usage_ratio: 0}) | del(.id)]'
) || containers_json="[]"

# --- Proxy request rate (last 1m) ---
proxy_requests_1m=0
CONTAINER_NAME="proxy-agent"
if docker container inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -q true; then
  proxy_requests_1m=$(docker logs --since 60s "${CONTAINER_NAME}" 2>&1 \
    | grep -c 'Forwarded request to backend' || true)
fi

# --- Output ---
jq -nc \
  --argjson cpu_load "${cpu_load_normalized}" \
  --argjson mem_total "${mem_total_bytes}" \
  --argjson mem_used "${mem_used_bytes}" \
  --argjson mem_ratio "${mem_usage_ratio}" \
  --argjson disks "${disk_json}" \
  --argjson containers "${containers_json}" \
  --argjson proxy_req "${proxy_requests_1m}" \
  '{cpu_load_normalized: $cpu_load, memory_total_bytes: $mem_total, memory_used_bytes: $mem_used, memory_usage_ratio: $mem_ratio, disks: $disks, containers: $containers, proxy_requests_1m: $proxy_req}'
