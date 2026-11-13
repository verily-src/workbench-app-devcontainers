#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh pgweb cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/pgweb-workload}"
