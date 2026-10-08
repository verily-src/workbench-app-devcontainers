#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly STATE_DIR="${1:-/var/lib/workbench-maintenance}"
jq -nc --slurpfile boot "$STATE_DIR/boot.json" --slurpfile ledger "$STATE_DIR/state.json" '
  {version: $boot[0].active_version, last_usable_version: $boot[0].last_usable_version,
    actions: ($ledger[0].actions | with_entries(.value = .value.status))}
' 2>/dev/null || printf 'null\n'
