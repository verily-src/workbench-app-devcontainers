#!/bin/bash

# Starts sshd on the sandbox-broker. Runs as root for sshd alone; sessions run as abc, the
# app's user, so the files agent-sandbox writes under the shared /config are the user's.

set -o errexit
set -o nounset
set -o pipefail

# The app's user and group, by the ids the shared volume carries. The account needs no password
# but must not be locked: a bare useradd writes "!" to the shadow entry, and sshd refuses a
# locked account whatever key it offers ("Permission denied (publickey)" on the client).
getent group abc > /dev/null || groupadd --gid 911 abc
id abc > /dev/null 2>&1 || useradd --uid 911 --gid 911 --home-dir /config --no-create-home --shell /bin/sh abc
# sshd runs the forced command through the account's shell. sh does not read the app user's
# /config/.bashrc, which is written for the app image (conda) and would print an error on
# every command here.
usermod -p '*' -s /bin/sh abc

# A host key that survives restarts, in its own volume.
mkdir -p /etc/ssh/keys
if [[ ! -f /etc/ssh/keys/ssh_host_ed25519_key ]]; then
  ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/keys/ssh_host_ed25519_key
fi

# What sessions need of this container's environment; sshd starts them clean.
{
  for name in OPENSHELL_GATEWAY_ENDPOINT OPENSHELL_TELEMETRY_ENABLED AGENT_MODEL_URL AGENT_CONTEXT_LENGTH \
      AGENT_MCP_URL AGENT_PORT_GUARD_STATUS AI_POLICY_DIR; do
    [[ -n "${!name:-}" ]] && printf 'export %s=%q\n' "${name}" "${!name}"
  done
} > /etc/sandbox-broker.env
chmod 644 /etc/sandbox-broker.env

mkdir -p /run/sshd

# A status file where the app's user can read it (the shared home): what this container found
# at start. Container logs are not reachable from the app, so this is the diagnostic.
status=/config/openshell/broker-status.txt
{
  echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "gateway: ${OPENSHELL_GATEWAY_ENDPOINT:-unset}"
  echo "account abc: $(getent shadow abc | cut -d: -f2 | sed 's/^\*$/unlocked, no password/; s/^!.*/LOCKED/')"
  if [[ -f /config/openshell/broker.pub ]]; then
    if su -s /bin/sh nobody -c '/opt/agent-sandbox/broker/authorized-keys.sh abc' | grep -q 'restrict,pty'; then
      echo "app key: /config/openshell/broker.pub readable and accepted"
    else
      echo "app key: /config/openshell/broker.pub present but not readable or not a key sshd takes"
    fi
  else
    echo "app key: /config/openshell/broker.pub not published yet (the app writes it on first use)"
  fi
  /usr/sbin/sshd -t -f /opt/agent-sandbox/broker/sshd_config 2>&1 && echo "sshd config: ok"
} > "${status}" 2>&1 || true
chown 911:911 "${status}" 2> /dev/null || true

# The sandbox's Google credential is the app's own, from the metadata server, and lasts an
# hour (the ai-policy README, "Data access"). Renew it every two minutes, as the app's user, for as long as
# this container runs; a refresh before the provider exists does nothing.
(
  while sleep 120; do
    su -s /bin/sh abc -c '. /etc/sandbox-broker.env; HOME=/config APP_USER_HOME=/config /opt/agent-sandbox/agent-sandbox.sh credential refresh' \
      > /dev/null 2>&1 || true
  done
) &

exec /usr/sbin/sshd -D -e -f /opt/agent-sandbox/broker/sshd_config
