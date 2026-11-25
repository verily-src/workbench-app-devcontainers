#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh playground cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/playground-workload}"
