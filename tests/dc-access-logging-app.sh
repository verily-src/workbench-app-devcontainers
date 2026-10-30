#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh dc-access-logging-app cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/dc-access-logging-app-workload}"
