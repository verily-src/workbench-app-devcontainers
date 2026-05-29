#!/bin/bash

# Docker ACR Authentication Setup
#
# This script configures Docker to use ACR
# for all ACR registries found in the current Terra Workbench environment.
# It modifies the user's Docker configuration to automatically authenticate
# with ACR repositories using Workbench credentials.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Currently a no-op: all images used in the prototype are public.
# ACR authentication will be implemented when private registry support is added.
echo "Azure docker-auth: no private registry authentication configured."