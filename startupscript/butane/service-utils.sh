#!/bin/bash
# service-utils defines helper functions for determining service path.

# Map the server to appropriate service path
function get_service_url() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_service_url <service> <server>" >&2
    return 1
  fi

  local service="$1"
  local server="$2"

  case "${server}" in
    "dev-stable") echo "https://workbench-dev.verily.com/api/${service}" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/${service}" ;;
    "test") echo "https://workbench-test.verily.com/api/${service}" ;;
    "prod") echo "https://workbench.verily.com/api/${service}" ;;
    *) return 1 ;;
  esac
}
readonly -f get_service_url

# Perform a curl request with the appropriate authorization header using the
# specified variable, temporarily disabling xtrace if it is enabled.
# Usage: curl_with_auth <TOKEN_VAR_NAME> <curl args>
# Example: curl_with_auth MY_TOKEN -s https://example.com/api with the token
#   stored in $MY_TOKEN
function curl_with_auth() {
  local token_var_name="${1:-TOKEN}"
  shift

  if [[ $- == *x* ]]; then
    { set +o xtrace; } 2>/dev/null
    trap 'set -o xtrace' RETURN
  fi

  if [[ -z "${!token_var_name}" ]]; then
    echo "Error: Variable '$token_var_name' is empty or not set." >&2
    return 1
  fi

  printf 'header = "Authorization: Bearer %s"' "${!token_var_name}" | curl -K - "$@"
}
readonly -f curl_with_auth
