#!/bin/bash
# sas-pre-deploy.sh — Runtime setup for SAS Analytics Pro on VWB GCE.
#
# Mounted at /opt/sas/aou/sas-pre-deploy.sh and invoked via PRE_DEPLOY_SCRIPT
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
# Chown only the directories we manage, not /data/workspace (contains gcsfuse mounts)
chown aou:aougroup /data
chown -R aou:aougroup /data/saswork /data/utilloc
