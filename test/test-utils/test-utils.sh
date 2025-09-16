#!/bin/bash

declare -a FAILED

function echoStderr() {
    echo "$@" 1>&2
}
readonly -f echoStderr

function check_user() {
    local test_user="$1"
    local label="$2"
    shift 2
    echo -e "\n🧪 Testing $label"
    if sudo -u "$test_user" bash -l -c "${SETUP_TEST}; $*"; then 
        echo "✅  Passed!"
        return 0
    else
        echoStderr "❌ $label check failed."
        FAILED+=("$label")
        return 1
    fi
}
readonly -f check_user

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

readonly SETUP_TEST="\
    set -o pipefail && \
    set -o errexit && \
    set -o nounset"
readonly SETUP_TEST
