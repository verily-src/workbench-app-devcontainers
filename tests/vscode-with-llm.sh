#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

tests/common/workload.sh vscode-with-llm cpu "${DEPENDENCY_WORKLOAD_OUTPUT:-/tmp/vscode-with-llm-workload}"
