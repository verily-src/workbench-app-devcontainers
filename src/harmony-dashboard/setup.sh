#!/usr/bin/env bash
set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive
${SUDO} apt-get update
${SUDO} apt-get install -y --no-install-recommends python3 python3-venv python3-pip
${SUDO} rm -rf /var/lib/apt/lists/*

${SUDO} mkdir -p /opt/harmony-venv
${SUDO} chown -R "$(id -u):$(id -g)" /opt/harmony-venv

python3 -m venv /opt/harmony-venv
/opt/harmony-venv/bin/pip install --no-cache-dir --upgrade pip
/opt/harmony-venv/bin/pip install --no-cache-dir -r /app/requirements.txt
