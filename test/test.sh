#!/bin/bash
cd "$(dirname "$0")" || exit
source test-utils.sh
sourceBashEnv

# Template specific tests
check "gcsfuse" which gcsfuse
check "wb cli" which wb
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"
check "cromwell" test -e "${CROMWELL_JAR}"
check "nextflow" which nextflow
check "dsub" test -e "${DSUB_VENV_PATH}/bin/dsub"

# Report result
reportResults
