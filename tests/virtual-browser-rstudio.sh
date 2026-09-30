#!/bin/bash
set -o errexit

export BACKEND_CONTAINER="application-server"
export APP_ORIGIN="app:8787"

bats tests/common/virtual-browser.bats
