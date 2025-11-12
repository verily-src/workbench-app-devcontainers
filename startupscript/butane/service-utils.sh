#!/bin/bash
# service-utils defines helper functions for determining service path.

# Map the server to appropriate service path
function get_service_url() {
  SERVER="$(get_metadata_value "terra-cli-server" "")"
  if [[ -z "${SERVER}" ]]; then
    SERVER="dev-stable"
  fi
  readonly SERVER


  case "${SERVER}" in
    "dev-stable") echo "https://workbench-dev.verily.com/api/${SERVER}" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/${SERVER}" ;;
    "test") echo "https://workbench-test.verily.com/api/${SERVER}" ;;
    "prod") echo "https://workbench.verily.com/api/${SERVER}" ;;
    *) return 1 ;;
  esac
}
readonly -f get_service_url