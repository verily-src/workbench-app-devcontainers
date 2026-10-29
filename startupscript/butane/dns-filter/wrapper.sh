#!/bin/bash
# wrapper.sh is this container's entrypoint (PID 1). dnsmasq cannot pick up a changed
# config file via a reload signal for the directives this filter relies on (server=/address=),
# so switching modes means actually stopping and restarting the dnsmasq process. This wrapper
# exists only to do that restart without affecting anything else on the VM.
#
# Starts dnsmasq against open.conf. On SIGUSR1, stops it and restarts against allowlist.conf.
set -eu

OPEN_CONF="/etc/dnsmasq.d/open.conf"
ALLOWLIST_CONF="/etc/dnsmasq.d/allowlist.conf"
CURRENT_CONF="${OPEN_CONF}"
DNSMASQ_PID=""

start_dnsmasq() {
  dnsmasq -k -C "${CURRENT_CONF}" --log-queries &
  DNSMASQ_PID=$!
}

stop_dnsmasq() {
  kill "${DNSMASQ_PID}" 2>/dev/null || true
  wait "${DNSMASQ_PID}" 2>/dev/null || true
}

# A repeat signal arriving while a handler is already running interrupts it mid-flight - bash
# does not queue or block a signal during its own trap - which can orphan dnsmasq or desync
# DNSMASQ_PID from reality (confirmed by reproducing the race locally). Ignore USR1/TERM/INT for
# the duration of each handler; switch_to_restricted re-arms them at the end, terminate() never
# needs to since it always exits.
switch_to_restricted() {
  trap '' USR1 TERM INT
  echo "wrapper: switching to restricted mode"
  CURRENT_CONF="${ALLOWLIST_CONF}"
  stop_dnsmasq
  start_dnsmasq
  trap switch_to_restricted USR1
  trap terminate TERM INT
}

terminate() {
  trap '' USR1 TERM INT
  echo "wrapper: terminating"
  stop_dnsmasq
  exit 0
}

trap switch_to_restricted USR1
trap terminate TERM INT

start_dnsmasq

while true; do
  # The `|| true` matters: when a trapped signal (switch/terminate) interrupts this wait, bash
  # returns the signal's exit status (128+N) from wait itself - without this guard, `set -e`
  # would kill the whole script (and the freshly-restarted dnsmasq) right after the trap ran.
  wait "${DNSMASQ_PID}" 2>/dev/null || true
  if kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
    # wait was interrupted by a trap (switch/terminate already handled it) - keep waiting.
    continue
  fi
  echo "wrapper: dnsmasq exited unexpectedly"
  exit 1
done
