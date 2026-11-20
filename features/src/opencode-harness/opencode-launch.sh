#!/bin/bash

# The `opencode` command in the app: always starts OpenCode inside the OpenShell sandbox, as
# the agent-sandbox feature's active harness. There is no unsandboxed mode. Arguments go to
# OpenCode in the sandbox (`opencode --version` included).

set -o errexit
set -o nounset
set -o pipefail

exec agent-sandbox run "$@"
