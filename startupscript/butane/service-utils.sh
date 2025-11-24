#!/bin/bash
# service-utils defines helper functions for determining service path.

# Map the server to appropriate service path
function get_service_url() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_service_url <service> <server>" >&2
    return 1
  fi

  local SERVICE="$1"
  local SERVER="$2"

  case "${SERVER}" in
    "dev-stable") echo "https://workbench-dev.verily.com/api/${SERVICE}" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/${SERVICE}" ;;
    "test") echo "https://workbench-test.verily.com/api/${SERVICE}" ;;
    "prod") echo "https://workbench.verily.com/api/${SERVICE}" ;;
    *) return 1 ;;
  esac
}
readonly -f get_service_url
