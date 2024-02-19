#!/bin/bash
cd $(dirname "$0")
source test-utils.sh

# Template specific tests
check "gcsfuse" which gcsfuse
check "wb cli" which wb
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"

# Report result
reportResults
