#!/bin/bash

declare -a FAILED

function echoStderr() {
    echo "$@" 1>&2
}
readonly -f echoStderr

function check() {
    LABEL=$1
    shift
    echo -e "\n🧪 Testing $LABEL"
    if bash -c "set -o pipefail; sourceBashRc; $*"; then 
        echo "✅  Passed!"
        return 0
    else
        echoStderr "❌ $LABEL check failed."
        FAILED+=("$LABEL")
        return 1
    fi
}
readonly -f check

function reportResults() {
    if [[ ${#FAILED[@]} -ne 0 ]]; then
        echoStderr -e "\n💥  Failed tests: " "${FAILED[@]}"
        exit 1
    else 
        echo -e "\n💯  All passed!"
        exit 0
    fi
}
readonly -f reportResults

function sourceBashRc() {
  for dir in /home/*; do
    if [[ -f "${dir}/.bashrc" ]]; then
      echo "Source ${dir}/.bashrc"
      source "${dir}/.bashrc"
    fi
  done
}
readonly -f sourceBashRc
export -f sourceBashRc
