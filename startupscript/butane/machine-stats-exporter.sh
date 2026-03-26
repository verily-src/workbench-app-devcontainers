#!/bin/bash
# machine-stats-exporter.sh
# Collects CPU, memory, and disk usage and prints a single JSON object
# to stdout. Run by a systemd timer so fluent-bit captures it from the journal.

set -o errexit
set -o nounset
set -o pipefail

# --- CPU ---
cpu_count=$(nproc)

# Load average (1m) normalized by CPU count — can exceed 1.0 under overload
# (e.g. waiting for I/O)
cpu_load=$(awk '{print $1}' /proc/loadavg)
cpu_load_normalized=$(awk "BEGIN {printf \"%.4f\", ${cpu_load}/${cpu_count}}")

# CPU utilization percent sampled over 1 second from /proc/stat
read -r _ u1 n1 s1 i1 w1 q1 f1 t1 _ < /proc/stat
sleep 1
read -r _ u2 n2 s2 i2 w2 q2 f2 t2 _ < /proc/stat
cpu_total=$(( (u2+n2+s2+i2+w2+q2+f2+t2) - (u1+n1+s1+i1+w1+q1+f1+t1) ))
cpu_idle=$(( (i2+w2) - (i1+w1) ))
if [ "${cpu_total}" -gt 0 ]; then
  cpu_usage_ratio=$(awk "BEGIN {printf \"%.4f\", (${cpu_total}-${cpu_idle})/${cpu_total}}")
else
  cpu_usage_ratio="0"
fi

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

# --- Proxy request rate (last 1m) ---
proxy_requests_1m=0
CONTAINER_NAME="proxy-agent"
if docker container inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -q true; then
  proxy_requests_1m=$(docker logs --since 60s "${CONTAINER_NAME}" 2>&1 \
    | grep -c 'Forwarded request to backend' || true)
fi

# --- Output ---
jq -nc \
  --argjson cpu "${cpu_usage_ratio}" \
  --argjson cpu_load "${cpu_load_normalized}" \
  --argjson mem_total "${mem_total_bytes}" \
  --argjson mem_used "${mem_used_bytes}" \
  --argjson mem_ratio "${mem_usage_ratio}" \
  --argjson disks "${disk_json}" \
  --argjson proxy_req "${proxy_requests_1m}" \
  '{cpu_usage_ratio: $cpu, cpu_load_normalized: $cpu_load, memory_total_bytes: $mem_total, memory_used_bytes: $mem_used, memory_usage_ratio: $mem_ratio, disks: $disks, proxy_requests_1m: $proxy_req}'
