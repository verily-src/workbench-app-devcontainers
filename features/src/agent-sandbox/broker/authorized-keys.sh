#!/bin/sh

# sshd's AuthorizedKeysCommand on the sandbox-broker: the app's key, read from the home the two
# containers share (broker-client.sh writes it). Only the app user; `restrict` turns off
# forwarding and the rest, `pty` turns a terminal back on for `run` and `shell`. The command a
# key may run is sshd_config's ForceCommand, not a key option, so this file cannot widen it.

[ "${1:-}" = abc ] || exit 0
key_file=/config/openshell/broker.pub
[ -f "${key_file}" ] || exit 0
grep -E '^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+' "${key_file}" | head -n 1 |
  sed 's/^/restrict,pty /'
