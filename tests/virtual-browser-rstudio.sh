#!/bin/bash
set -o errexit

export BACKEND_CONTAINER="application-server"
export APP_ORIGIN="application-server:8787"

bats tests/common/virtual-browser.bats
