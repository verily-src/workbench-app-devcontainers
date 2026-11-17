#!/bin/bash
set -o errexit
export TEST_USER="pn"

bats tests/common/base.bats
bats tests/mdv.bats
