#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh test-app cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/test-app-workload}"
