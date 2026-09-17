#!/bin/bash
# setup-rstudio-env.sh — Populate AoU environment variables for R sessions.
#
# Runs after post-startup.sh (or remount-on-restart.sh) to write AoU variables
# into Renviron.site so that R sessions can access them via Sys.getenv().

set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1}"
readonly RENVIRON_SITE="/usr/local/lib/R/etc/Renviron.site"

sudo -u "${USER_NAME}" bash -c 'source "$HOME/load-env.sh"' || true

HOME_DIR="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
if [ -f "${HOME_DIR}/.aou-env" ]; then
  sed -i '/### BEGIN: AoU ###/,/### END: AoU ###/d' "${RENVIRON_SITE}"
  {
    echo "### BEGIN: AoU ###"
    sed 's/^export //' "${HOME_DIR}/.aou-env"
    echo "### END: AoU ###"
  } >> "${RENVIRON_SITE}"
fi
