#!/bin/bash

# This test file will be executed against an auto-generated devcontainer.json that
# includes the 'ttyd' feature with various options.

set -e

# Optional: Import test library bundled with the devcontainer CLI
# See https://github.com/devcontainers/cli/blob/HEAD/docs/features/test.md#dev-container-features-test-lib
# Provides the 'check' command to execute tests and the 'reportResults' function to report results.
source dev-container-features-test-lib

# Feature-specific tests
# The 'check' command takes a label and a command to run.

check "ttyd installed" which ttyd

check "ttyd version" ttyd --version

check "ttyd executable" bash -c "ttyd --version 2>&1 | grep -E 'ttyd version [0-9]+\.[0-9]+\.[0-9]+'"

check "ttyd help" ttyd --help

# Report result
# If any of the checks above exited with a non-zero exit code, the test will fail.
reportResults
