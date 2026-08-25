#!/bin/bash
set -o errexit

export BACKEND_CONTAINER="rstudio"
export APP_ORIGIN="http://rstudio:8787"

bats tests/common/virtual-browser.bats
