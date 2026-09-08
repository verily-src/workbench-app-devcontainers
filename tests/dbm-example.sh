#!/bin/bash
set -o errexit
export TEST_USER="jovyan"
export TEST_USER_HOME="/home/jovyan"

bats tests/common/base.bats
