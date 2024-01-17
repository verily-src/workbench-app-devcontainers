#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

if [ $# -ne 2 ]; then
  echo "Usage: $0 user workDirectory"
  exit 1
fi

user="$1"
workDirectory="$2"

# Gets absolute path of the script directory. 
# Because the script sometimes cd to other directoy (e.g. /tmp), 
# absolute path is more reliable.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
#######################################
# Emit a message with a timestamp
#######################################
source ${SCRIPT_DIR}/emit.sh

function get_metadata_value() {
 local metadata_path="${1}"
 curl --retry 5 -s -f \
   -H "Metadata-Flavor: Google" \
   "http://metadata/computeMetadata/v1/${metadata_path}"
}

readonly RUN_AS_LOGIN_USER="sudo -u ${user} bash -l -c"

readonly USER_BASH_COMPLETION_DIR="${workDirectory}/.bash_completion.d"
readonly USER_HOME_LOCAL_SHARE="${workDirectory}/.local/share"
readonly USER_WORKBENCH_CONFIG_DIR="${workDirectory}/.workbench"
readonly USER_WORKBENCH_LEGACY_CONFIG_DIR="${workDirectory}/.terra"
readonly USER_SSH_DIR="${workDirectory}/.ssh"
readonly USER_BASHRC="${workDirectory}/.bashrc"
readonly USER_BASH_PROFILE="${workDirectory}/.bash_profile"
readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/post-startup-output.txt"

readonly JAVA_INSTALL_TMP="${USER_WORKBENCH_CONFIG_DIR}/javatmp"

# Variables for Workbench-specific code installed on the VM
readonly WORKBENCH_INSTALL_PATH="/usr/bin/wb"
readonly WORKBENCH_LEGACY_PATH="/usr/bin/terra"

readonly WORKBENCH_GIT_REPOS_DIR="${workDirectory}/repos"

# Move to the /tmp directory to let any artifacts left behind by this script can be removed.
cd /tmp || exit

# Send stdout and stderr from this script to a file for debugging.
# Make the .workbench directory as the user so that they own it and have correct linux permissions.
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_WORKBENCH_CONFIG_DIR}'"
${RUN_AS_LOGIN_USER} "ln -sf '${USER_WORKBENCH_CONFIG_DIR}' '${USER_WORKBENCH_LEGACY_CONFIG_DIR}'"
exec >> "${POST_STARTUP_OUTPUT_FILE}"
exec 2>&1

# The apt package index may not be clean when we run; resynchronize
apt-get update
apt install -y jq curl tar

# Create the target directories for installing into the HOME directory
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"

# As described above, have the ~/.bash_profile source the ~/.bashrc
cat << EOF >> "${USER_BASH_PROFILE}"

if [[ -e ~/.bashrc ]]; then
 source ~/.bashrc
fi

EOF

# Indicate the start of Workbench customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

# Prepend "/usr/bin" (if not already in the path)
if [[ "${PATH}:" != "/usr/bin:"* ]]; then
  export PATH=/usr/bin:${PATH}
fi
EOF

source ${SCRIPT_DIR}/install-java.sh

# Install & configure the Workbench CLI
emit "Installing the Workbench CLI ..."

# Fetch the Workbench CLI server environment from the metadata server to install appropriate CLI version
TERRA_SERVER="$(get_metadata_value "instance/attributes/terra-cli-server")"
if [[ -z "${TERRA_SERVER}" ]]; then
  TERRA_SERVER="verily"
fi
readonly TERRA_SERVER

# If the server environment is a verily server, use the verily download script.
if [[ "${TERRA_SERVER}" == *"verily"* ]]; then
  # Map the CLI server to appropriate AFS service path and fetch the CLI distribution path
  if ! versionJson="$(curl -s "https://${TERRA_SERVER/verily/terra}-axon.api.verily.com/version")"; then
    >&2 echo "ERROR: Failed to get version file from ${TERRA_SERVER}"
    exit 1
  fi
  cliDistributionPath="$(echo ${versionJson} | jq -r '.cliDistributionPath')"

  ${RUN_AS_LOGIN_USER} "curl -L https://storage.googleapis.com/${cliDistributionPath#gs://}/download-install.sh | TERRA_CLI_SERVER=${TERRA_SERVER} bash"
  cp wb "${WORKBENCH_INSTALL_PATH}"
else
  >&2 echo "ERROR: ${TERRA_SERVER} is not a known Workbench server"
  exit 1
fi

# Copy 'wb' to its legacy 'terra' name.
cp "${WORKBENCH_INSTALL_PATH}" "${WORKBENCH_LEGACY_PATH}"

# Set browser manual login since that's the only login supported from a Vertex AI Notebook VM
${RUN_AS_LOGIN_USER} "wb config set browser MANUAL"

# Set the CLI server based on the server that created the VM.
${RUN_AS_LOGIN_USER} "wb server set --name=${TERRA_SERVER}"

# Log in with app-default-credentials
${RUN_AS_LOGIN_USER} "wb auth login --mode=APP_DEFAULT_CREDENTIALS"

# Generate the bash completion script
${RUN_AS_LOGIN_USER} "wb generate-completion > '${USER_BASH_COMPLETION_DIR}/workbench'"


####################################
# Shell and notebook environment
####################################

# Set the CLI workspace id using the VM metadata, if set.
readonly TERRA_WORKSPACE="$(get_metadata_value "instance/attributes/terra-workspace-id")"
if [[ -n "${TERRA_WORKSPACE}" ]]; then
 ${RUN_AS_LOGIN_USER} "wb workspace set --id='${TERRA_WORKSPACE}'"
fi


#################
# bash completion
#################
source ${SCRIPT_DIR}/bash-completion.sh

###############
# git setup
###############
source ${SCRIPT_DIR}/git-setup.sh

#############################
# Mount buckets
#############################
# Installs gcsfuse if it is not already installed.
if ! which gcsfuse >/dev/null 2>&1; then
  emit "Installing gcsfuse..."
  # install packages needed to install gcsfuse
  apt-get install -y \
    fuse \
    lsb-core

  # Install based on gcloud docs here https://cloud.google.com/storage/docs/gcsfuse-install.
  export GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)" \
    && echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" | tee /etc/apt/sources.list.d/gcsfuse.list \
    && curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
  apt-get update \
    && apt-get install -y gcsfuse
else
  emit "gcsfuse already installed. Skipping installation."
fi

${RUN_AS_LOGIN_USER} "wb resource mount"
