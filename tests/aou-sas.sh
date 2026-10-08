#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh aou-sas cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/aou-sas-workload}"
