#!/bin/bash

# Docker ACR Authentication Setup
#
# This script authenticates Docker with Azure Container Registry (ACR) registries
# found in the current Terra Workbench environment. It uses the VM's managed identity
# to obtain ACR refresh tokens for docker login.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Currently a no-op: all images used in the prototype are public.
# ACR authentication will be implemented when private registry support is added.
echo "Azure docker-auth: no private registry authentication configured."