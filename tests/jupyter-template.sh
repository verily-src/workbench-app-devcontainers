#!/bin/bash
set -o errexit
export TEST_USER="jupyter"

bats tests/common/base.bats
