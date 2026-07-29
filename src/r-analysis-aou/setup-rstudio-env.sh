#!/bin/bash
# setup-rstudio-env.sh — Populate ~/.aou-env for R sessions.
#
# Runs after post-startup.sh (or remount-on-restart.sh) to pre-warm the
# load-env cache so that rsession-profile can source it without blocking
# R session startup on an API call.

set -o errexit
set -o nounset
set -o pipefail

readonly USER_NAME="${1}"
sudo -u "${USER_NAME}" bash -c 'source "$HOME/load-env.sh"' || true
