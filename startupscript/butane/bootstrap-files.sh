#!/bin/bash
# bootstrap-files.sh downloads the necessary scripts and files for the
# devcontainer startup script to run. This should be run on system boot, before
# any services are started.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

BRANCH="${1:?Usage: bootstrap-files.sh <branch> <cloud> <build_only>}"
CLOUD="${2:?Usage: bootstrap-files.sh <branch> <cloud> <build_only>}"
BUILD_ONLY="${3:?Usage: bootstrap-files.sh <branch> <cloud> <build_only>}"

BASE_URL="https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/${BRANCH}/startupscript/butane"

download() {
  local dest="$1"
  local src="$2"
  local mode="${3:-0755}"
  mkdir -p "$(dirname "$dest")"
  curl --retry 5 --retry-delay 2 --retry-all-errors -fsSL -o "$dest" "${BASE_URL}/${src}"
  chmod "$mode" "$dest"
}

# Cloud-specific scripts
download /home/core/docker-auth.sh "${CLOUD}/docker-auth.sh"
download /opt/bin/docker-credential-workbench-secret "${CLOUD}/docker-credential-workbench-secret"
download /home/core/metadata-utils.sh "${CLOUD}/metadata-utils.sh"
download /home/core/wb/values.sh "${CLOUD}/wb-values.sh"
download /etc/fluent-bit.conf "${CLOUD}/fluent-bit.conf" 0644

# AWS-only scripts
if [ "$CLOUD" = "aws" ]; then
  download /home/core/docker-repositories.sh "aws/docker-repositories.sh"
  download /opt/bin/docker-credential-workbench-ecr "aws/credential-helper.sh"
fi

# Common scripts
download /home/core/install-node.sh "010-install-node.sh"
download /home/core/create-docker-network.sh "020-create-docker-network.sh"
download /home/core/configure-wb.sh "030-configure-wb.sh"
download /home/core/register-key.sh "035-register-key.sh"
download /home/core/git-clone-devcontainer.sh "040-git-clone-devcontainer.sh"
download /home/core/parse-devcontainer.sh "050-parse-devcontainer.sh"
download /home/core/provide-secrets.sh "055-provide-secrets.sh"
download /home/core/start-proxy-agent.sh "060-start-proxy-agent.sh"
download /home/core/devcontainer.sh "devcontainer.sh"
download /home/core/pre-devcontainer.sh "pre-devcontainer.sh"
download /home/core/devcontainer-failure-handler.sh "devcontainer-failure-handler.sh"
download /home/core/package.json "package.json"
download /home/core/package-lock.json "package-lock.json"
download /home/core/jsoncStripComments.mjs "jsoncStripComments.mjs"
download /home/core/probe-proxy-readiness.sh "probe-proxy-readiness.sh"
download /home/core/probe-user-access.sh "probe-user-access.sh"
download /home/core/idle-shutdown.sh "idle-shutdown.sh"
download /home/core/prefetch-oci-features.sh "prefetch-oci-features.sh"
download /home/core/check-for-newer-os-update.sh "check-for-newer-os-update.sh"
download /home/core/metadata-cleanup.sh "metadata-cleanup.sh"
download /home/core/monitoring-utils.sh "monitoring-utils.sh"
download /home/core/machine-stats-exporter.sh "machine-stats-exporter.sh"
download /home/core/service-utils.sh "service-utils.sh"
download /home/core/secret-utils.sh "secret-utils.sh"
download /home/core/docker-credential-secrets.sh "docker-credential-secrets.sh"
download /home/core/docker-auth-secrets.sh "docker-auth-secrets.sh"
download /home/core/run-fluent-bit.sh "run-fluent-bit.sh"
download /etc/fluent-bit/severity.lua "severity.lua" 0644
download /home/core/wb/Dockerfile "wb/Dockerfile" 0644
download /home/core/wb.sh "wb/wb.sh"
download /oem/bin/oem-postinst "oem-postinst"

# Build-only scripts
if [ "$BUILD_ONLY" = "true" ]; then
  download /home/core/prepare-devcontainer-cache.sh "prepare-devcontainer-cache.sh"
fi
