#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh workbench-jupyter-docker cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/workbench-jupyter-docker-workload}"
