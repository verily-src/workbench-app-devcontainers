#!/bin/bash
set -o errexit

export BACKEND_CONTAINER="jupyterlab"
export APP_ORIGIN="jupyterlab:8888"

bats tests/common/virtual-browser.bats
