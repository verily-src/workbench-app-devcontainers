#!/bin/bash
set -o errexit
export TEST_USER="jupyter"

bats tests/common/base.bats
bats tests/common/workbench-tools.bats
bats tests/common/postgres-client.bats
