#!/bin/bash
# sas-post-deploy.sh — Lock down the SAS license after it has been applied.
#
# Invoked via POST_DEPLOY_SCRIPT after SAS services start.  The license must
# be readable by the sas user during application (PRE_DEPLOY), but afterward
# we restrict it to root so the aou user cannot exfiltrate it via pipe commands.

if [ -f /sasinside/SASLicense.jwt ]; then
  chmod 400 /sasinside/SASLicense.jwt
  chown root:root /sasinside/SASLicense.jwt
fi
