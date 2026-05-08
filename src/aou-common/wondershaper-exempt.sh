#!/bin/sh
# wondershaper-exempt.sh — Exempt restricted.googleapis.com and internal
# VPC traffic from wondershaper upload rate limiting.
#
# Mounted into the wondershaper container and run as a wrapper entrypoint.
# Launches the exemption logic in the background, then exec's the original
# wondershaper command (passed as arguments).
#
# Why these exemptions are safe:
#   - restricted.googleapis.com (199.36.153.4/30): all access is scoped by
#     the VPC Service Perimeter; cross-perimeter exfiltration is blocked at
#     the platform level regardless of bandwidth.
#   - Internal VPC (10.0.0.0/8): covers Dataproc master-to-worker traffic;
#     this is intra-cluster communication that never leaves the VPC.

add_exemptions() {
  IFACE=$(ip route | grep default | awk '{print $5}' | head -1)
  [ -z "$IFACE" ] && IFACE="eth0"

  # Wait for wondershaper to set up its tc qdisc.
  attempts=0
  while ! tc qdisc show dev "$IFACE" 2>/dev/null | grep -qE "htb|cbq|tbf|hfsc"; do
    sleep 1
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 60 ]; then
      echo "wondershaper-exempt: timeout waiting for tc rules on $IFACE" >&2
      return 1
    fi
  done

  # Determine the root qdisc handle (e.g., "1:" from "qdisc htb 1: root ...").
  ROOT=$(tc qdisc show dev "$IFACE" | grep -E "htb|cbq|tbf|hfsc" | head -1 | awk '{print $3}')
  [ -z "$ROOT" ] && ROOT="1:"

  # Exempt restricted.googleapis.com (199.36.153.4/30).
  tc filter add dev "$IFACE" parent "$ROOT" protocol ip prio 1 \
    u32 match ip dst 199.36.153.4/30 flowid "$ROOT" 2>/dev/null

  # Exempt internal VPC traffic (GCE uses 10.x.x.x for internal IPs,
  # covering Dataproc master-to-worker communication).
  tc filter add dev "$IFACE" parent "$ROOT" protocol ip prio 1 \
    u32 match ip dst 10.0.0.0/8 flowid "$ROOT" 2>/dev/null

  echo "wondershaper-exempt: exemptions active on $IFACE (restricted.googleapis.com + internal VPC)"
}

# Run exemption logic in the background so it doesn't block startup.
add_exemptions &

# Hand off to the original wondershaper entrypoint / command.
exec "$@"
