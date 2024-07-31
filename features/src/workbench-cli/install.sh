#!/bin/bash

set -e

# Install & configure the Workbench CLI

echo "Installing the Workbench CLI ..."

USER=${USER:-"$_CONTAINER_USER"}
USER_HOME=${USER_HOME:-"$_CONTAINER_USER_HOME"}
CLOUD=${CLOUD:-"gcp"}
WORKSPACE=${WORKSPACE:-""}
SERVER=${SERVER:-"verily"}
LOGIN=${LOGIN:-"true"}
MOUNT=${MOUNT:-"true"}

if [[ "${SERVER}" != *"verily"* ]]; then
  echo "ERROR: ${SERVER} is not a known Workbench server"
  exit 1
fi

readonly RUN_AS_LOGIN_USER="su -s /bin/bash -p ${USER} -c"
readonly WORKBENCH_INSTALL_PATH="/usr/bin/wb"
readonly WORKBENCH_LEGACY_PATH="/usr/bin/terra"

# Some 'linuxserver' images fix the permissions of the /config (HOME) dir as part
# of a startup script.  We need to fix it here, so our can properly install the CLI
# as the user.
chown "${USER}" "${USER_HOME}"

# Map the CLI server to appropriate AFS service path and fetch the CLI distribution path
if ! versionJson="$(curl -s "https://${SERVER/verily/terra}-axon.api.verily.com/version")"; then
  echo "ERROR: Failed to get version file from ${SERVER}"
  exit 1
fi
cliDistributionPath="$(echo "${versionJson}" | jq -r '.cliDistributionPath')"

if [ -f "${SDKMAN_DIR}/bin/sdkman-init.sh" ]; then
  JAVA_ENV_PREFIX=". \${SDKMAN_DIR}/bin/sdkman-init.sh && "
else
  JAVA_ENV_PREFIX=""
fi
readonly JAVA_ENV_PREFIX

cd /tmp
java -version
${RUN_AS_LOGIN_USER} "${JAVA_ENV_PREFIX} curl -L https://storage.googleapis.com/${cliDistributionPath#gs://}/download-install.sh | TERRA_CLI_SERVER=${SERVER} bash"
cp wb "${WORKBENCH_INSTALL_PATH}"
cp wb "${WORKBENCH_LEGACY_PATH}"

# Set browser manual login since that's the only login supported from a Vertex AI Notebook VM
${RUN_AS_LOGIN_USER} "wb config set browser MANUAL"

# Set the CLI server based on the server that created the VM.
${RUN_AS_LOGIN_USER} "wb server set --name=${SERVER}"

# Generate the bash completion script
${RUN_AS_LOGIN_USER} "mkdir -p ${USER_HOME}/.bash_completion.d"
${RUN_AS_LOGIN_USER} "wb generate-completion > '${USER_HOME}/.bash_completion.d/workbench'"

if [[ "${LOGIN}" != "true" ]]; then
  echo "Skipping Workbench CLI login."
  exit 0
fi

# For GCP use "APP_DEFAULT_CREDENTIALS", for AWS use "AWS_IAM" as --mode arg to "wb auth login".
LOG_IN_MODE="APP_DEFAULT_CREDENTIALS"
if [[ "${CLOUD}" == "aws" ]]; then
  LOG_IN_MODE="AWS_IAM"
fi
readonly LOG_IN_MODE

# Log in with app-default-credentials
echo "Logging into workbench CLI with mode ${LOG_IN_MODE}"
ls -al /workspace
${RUN_AS_LOGIN_USER} "ls -al /workspace"
${RUN_AS_LOGIN_USER} "wb auth login --mode=${LOG_IN_MODE} || cat /config/.workbench/logs/workbench.log"

if [[ -z "${WORKSPACE}" ]]; then
  echo "No workspace provided."
  exit 0
fi
${RUN_AS_LOGIN_USER} "wb workspace set --id='${WORKSPACE}'"

if [[ "${MOUNT}" == "true" ]]; then
  if ! which gcsfuse >/dev/null 2>&1; then
    echo "Installing gcsfuse..."

    apt-get install -y \
      fuse \
      lsb-release

    # Install based on gcloud docs here https://cloud.google.com/storage/docs/gcsfuse-install.
    GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)"
    readonly GCSFUSE_REPO

    echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" > /etc/apt/sources.list.d/gcsfuse.list
    curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
    apt-get update \
      && apt-get install -y gcsfuse
  else
    echo "gcsfuse already installed. Skipping installation."
  fi

  # Uncomment user_allow_other in the fuse.conf to enable non-root user to mount files with -o allow-other option.
  sed -i '/user_allow_other/s/^#//g' /etc/fuse.conf

  ${RUN_AS_LOGIN_USER} "wb resource mount --allow-other"
fi
