#!/bin/bash
set -o errexit
export TEST_USER="vscode"

bats tests/common/base.bats
