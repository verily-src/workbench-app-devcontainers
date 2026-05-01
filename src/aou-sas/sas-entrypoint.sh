#!/bin/bash
# sas-entrypoint.sh — Wrapper entrypoint for Mikey Secrets integration.
#
# When the Mikey Secrets system is active, the Secret Receiver delivers the
# SAS license via a file descriptor and sets SAS_LICENSE_PATH.  This script
# copies the license to /sasinside/SASLicense.jwt where the SAS Analytics
# Pro entrypoint expects it.
#
# When SAS_LICENSE_PATH is not set (manual GCE testing), this script is a
# no-op passthrough — SAS reads the license from the bind-mounted /sasinside/.

if [ -n "${SAS_LICENSE_PATH:-}" ]; then
  mkdir -p /sasinside
  cp "$SAS_LICENSE_PATH" /sasinside/SASLicense.jwt
  chmod 400 /sasinside/SASLicense.jwt
  chown root:root /sasinside/SASLicense.jwt
fi

exec /opt/sas/viya/home/bin/sas-analytics-pro-entrypoint.sh "$@"
