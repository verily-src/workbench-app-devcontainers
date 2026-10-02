#!/bin/bash
set -o errexit

export BACKEND_CONTAINER="application-server"
export APP_ORIGIN="application-server:8888"

bats tests/common/virtual-browser.bats
