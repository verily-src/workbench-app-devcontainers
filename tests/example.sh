#!/bin/bash
set -o errexit
export TEST_USER="jovyan"

bats tests/common/base.bats
