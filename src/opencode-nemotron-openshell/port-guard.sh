#!/bin/sh

# Drops connections to code-server's port that arrive on the VM's network card,
# so other VMs in the network cannot reach it without Workbench sign-in. The
# Workbench proxy agent dials out and reaches the port locally, so it is not
# affected. Runs in the port-guard container on the host network.
#
# The rule goes in the raw table, before Docker's NAT, through every iptables
# backend present (nft and legacy), so it applies whichever one Docker uses. It
# is re-applied every minute in case something resets the table. The status,
# including the rule's packet counters, is written to /status/port-guard, which
# the app container reads (`opencode-sandbox status`, `opencode-sandbox selftest`).

set -u

readonly PORT="${GUARDED_PORT:-8443}"
readonly STATUS="${PORT_GUARD_STATUS_FILE:-/status/port-guard}"
readonly ERRORS="/tmp/port-guard.err"

write_status() {
  cat > "${STATUS}.tmp" && mv "${STATUS}.tmp" "${STATUS}"
}

if ! apk add --no-cache iptables iptables-legacy > /dev/null 2> "${ERRORS}"; then
  printf 'state=error\ntime=%s\nerror=could not install iptables: %s\n' \
    "$(date -u +%s)" "$(tail -c 300 "${ERRORS}")" | write_status
  exit 1
fi

while true; do
  : > "${ERRORS}"
  nic="$(ip route show default | awk '{print $5; exit}')"
  applied=""
  rules=""
  if [ -n "${nic}" ]; then
    for ipt in iptables-nft iptables-legacy; do
      command -v "${ipt}" > /dev/null 2>&1 || continue
      if "${ipt}" -t raw -C PREROUTING -i "${nic}" -p tcp --dport "${PORT}" -j DROP 2> /dev/null ||
        "${ipt}" -t raw -I PREROUTING -i "${nic}" -p tcp --dport "${PORT}" -j DROP 2>> "${ERRORS}"; then
        applied="${applied} ${ipt}"
      fi
      rules="${rules}# ${ipt}
$("${ipt}" -t raw -L PREROUTING -v -n -x 2>&1)
"
    done
  fi
  state=ok
  if [ -z "${nic}" ] || [ -z "${applied}" ]; then
    state=error
  fi
  printf 'state=%s\ntime=%s\nport=%s\nnic=%s\nbackends=%s\n--- raw PREROUTING (packet counters show dropped connections)\n%s--- errors\n%s\n' \
    "${state}" "$(date -u +%s)" "${PORT}" "${nic:-none}" "${applied# }" "${rules}" "$(tail -c 500 "${ERRORS}")" |
    write_status
  sleep 60
done
