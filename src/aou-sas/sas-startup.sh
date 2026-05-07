#!/bin/bash
# sas-startup.sh — Runtime setup for SAS Analytics Pro on VWB GCE.
#
# Mounted at /opt/sas/aou/sas-startup.sh and invoked via PRE_DEPLOY_SCRIPT
# before SAS services start.  Only handles steps that depend on the /data
# volume or runtime state; build-time setup is in the Dockerfile.
#
# All steps are idempotent so container restarts are fast.

set -o errexit
set -o nounset
set -o pipefail

###############################################################################
# Data directories (on the sas-data volume)
###############################################################################
mkdir -p /data/saswork /data/utilloc
chown -R aou:aougroup /data

###############################################################################
# Lock down the SAS license so the aou user cannot read it via pipe commands.
# The entrypoint wrapper already sets root:root 0400 for Mikey Secrets, but
# this covers the bind-mount fallback and acts as defence in depth.
###############################################################################
if [ -f /sasinside/SASLicense.jwt ]; then
  chown root:root /sasinside/SASLicense.jwt
  chmod 400 /sasinside/SASLicense.jwt
fi

###############################################################################
# AoU environment loader (staged in Dockerfile at /opt/sas/aou/)
###############################################################################
if [ -d /opt/sas/aou ]; then
  cp -n /opt/sas/aou/load-env /opt/sas/aou/load-env.sh /data/ 2>/dev/null || true
  chown aou:aougroup /data/load-env /data/load-env.sh 2>/dev/null || true
  grep -q "load-env.sh" /data/.bashrc 2>/dev/null || \
    echo "source /data/load-env.sh" >> /data/.bashrc
fi
