#!/bin/bash
#
# Name: startup.sh
#
# NOTE FOR CONTRIBUTORS:
#   This startup script closely mirrors the startup script used for Vertex AI Notebook instances here: service/src/main/java/bio/terra/workspace/service/resource/controlled/cloud/gcp/ainotebook/post-startup.sh.
#   Please ensure that changes to shared logic are reflected in both scripts.
#
# Description:
#   Default startup script to setup Workbench configurations in a Dataproc cluster manager node.
#
# Metadata and guest attributes:
#   This script uses the following GCE metadata and guest attributes for startup orchestration:
#   - attributes/dataproc-role: Read by the script to determine if it's running on the manager node or a worker node. Possible values are "Master" or "Worker".
#   - instance/guest-attributes/startup_script/status: Set by this script, storing the status of this script's execution. Possible values are "STARTED", "COMPLETE", or "ERROR".
#   - instance/guest-attributes/startup_script/message: Set by this script, storing the message of this script's execution. If the status is "ERROR", this message will contain an error message, otherwise it will be empty.
#   - instance/attributes/terra-cli-server: Read by this script to configure the Workbench CLI server.
#   - instance/attributes/terra-workspace-id: Read by this script to configure the Workbench CLI workspace.
#   - instance/attributes/software-framework: Read by this script to optionally install software on the cluster manager node. Currently supported value is: "HAIL".
#
# Execution details:
#   By default, this script is executed as root on all Dataproc vm nodes on every startup.
#   However, the script will exit early if it's not running on the Dataproc manager node and also if it's not the first time the script is run.
#   NOTE: This script is executed before the dataproc startup script that installs software components and jupyter.
#
# How to test changes to this file:
#   Copy this file to a GCS bucket:
#   - gsutil cp startupscript/dataproc/startup.sh gs://MYBUCKET
#
#   Create a new VM (JupyterLab provided by Dataproc spark):
#   - terra resource create dataproc-cluster \
#       --name=test_dataproc_startup \
#       --metadata=startup-script-url=gs://MYBUCKET/startup.sh
#
#   To test a new command in this script, be sure to run with "sudo" in a JupyterLab Terminal.
#
# Integration Tests
#   Please also make sure integration test `PrivateControlledDataprocClusterStartup` passes. Refer to
#   https://github.com/DataBiosphere/terra-workspace-manager/tree/main/integration#Run-nightly-only-test-suite-locally
#   for instruction on how to run the test.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Only run on the dataproc manager node. Exit silently if otherwise.
readonly ROLE=$(/usr/share/google/get_metadata_value attributes/dataproc-role)
if [[ "${ROLE}" != 'Master' ]]; then exit 0; fi

# Only run on first startup. A file is created in the exit handler in the case of successful startup execution.
readonly STARTUP_SCRIPT_COMPLETE="/etc/startup_script_complete"
if [[ -f "${STARTUP_SCRIPT_COMPLETE}" ]]; then exit 0; fi

# The linux user that JupyterLab will be running as. It's important to do some parts of setup in the
# user space, such as setting Workbench CLI settings which are persisted in the user's $HOME.
readonly LOGIN_USER="dataproc"

# Create an alias for cases when we need to run a shell command as the login user.
# Note that we deliberately use "bash -l" instead of "sh" in order to get bash (instead of dash)
# and to pick up changes to the .bashrc.
#
# This is intentionally not a Bash function, as that can suppress error propagation.
# This is intentionally not a Bash alias as they are not supported in shell scripts.
readonly RUN_AS_LOGIN_USER="sudo -u ${LOGIN_USER} bash -l -c"

# Set variables for key binaries to ensure we pick up the ones we want (that may not always be in PATH)
readonly RUN_PIP="/opt/conda/miniconda3/bin/pip"
readonly RUN_PYTHON="/opt/conda/miniconda3/bin/python"
readonly RUN_JUPYTER="/opt/conda/miniconda3/bin/jupyter"

# Startup script status is propagated out to VM guest attributes
readonly STATUS_ATTRIBUTE="startup_script/status"
readonly MESSAGE_ATTRIBUTE="startup_script/message"

# Create tool installation directories.
readonly USER_HOME_DIR="/home/${LOGIN_USER}"
readonly USER_BASH_COMPLETION_DIR="${USER_HOME_DIR}/.bash_completion.d"
readonly USER_HOME_LOCAL_DIR="${USER_HOME_DIR}/.local"
readonly USER_HOME_LOCAL_BIN="${USER_HOME_DIR}/.local/bin"
readonly USER_HOME_LOCAL_SHARE="${USER_HOME_DIR}/.local/share"
readonly USER_WORKBENCH_CONFIG_DIR="${USER_HOME_DIR}/.workbench"
readonly USER_WORKBENCH_LEGACY_CONFIG_DIR="${USER_HOME_DIR}/.terra"
readonly USER_SSH_DIR="${USER_HOME_DIR}/.ssh"

# Proxy override variables.
readonly PROXY_AGENT_BANNER="/opt/dataproc/proxy-agent/banner.html"
readonly PROXY_AGENT_SERVICE="google-dataproc-component-gateway.service"

# For consistency across these two environments, this startup script writes
# to the ~/.bashrc, and has the ~/.bash_profile source the ~/.bashrc
readonly USER_BASHRC="${USER_HOME_DIR}/.bashrc"
readonly USER_BASH_PROFILE="${USER_HOME_DIR}/.bash_profile"

readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/post-startup-output.txt"
readonly WORKBENCH_BOOT_SERVICE_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/boot-output.txt"

readonly JUPYTER_SERVICE_NAME="jupyter.service"
readonly JUPYTER_SERVICE="/etc/systemd/system/${JUPYTER_SERVICE_NAME}"
readonly JUPYTER_CONFIG="/etc/jupyter/jupyter_notebook_config.py"

readonly WORKBENCH_PROXY_AGENT_SERVICE_NAME="workbench-proxy-agent.service"
readonly WORKBENCH_PROXY_AGENT_SERVICE="/etc/systemd/system/${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"

# Variables relevant for 3rd party software that gets installed
readonly REQ_JAVA_VERSION=17
readonly JAVA_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/java"
readonly JAVA_INSTALL_TMP="${USER_WORKBENCH_CONFIG_DIR}/javatmp"

readonly NEXTFLOW_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/nextflow"

readonly CROMWELL_LATEST_VERSION=81
readonly CROMWELL_INSTALL_DIR="${USER_HOME_LOCAL_SHARE}/java"
readonly CROMWELL_INSTALL_JAR="${CROMWELL_INSTALL_DIR}/cromwell-${CROMWELL_LATEST_VERSION}.jar"

readonly CROMSHELL_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/cromshell"

# We need to set the correct Java installation for the Workbench CLI (17) which conflicts with the
# version that Hail needs (8 or 11).
#
# We can't set up aliases or bash functions in the .bashrc (as they won't be available in Jupyter notebooks).
# Instead, let's create a wrapper script for the wb command.
readonly WORKBENCH_COMMAND_PATH="${USER_HOME_LOCAL_BIN}/wb_cli"
readonly WORKBENCH_WRAPPER_PATH="${USER_HOME_LOCAL_BIN}/wb"

# Variables for Workbench-specific code installed on the VM
readonly WORKBENCH_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/wb"
readonly WORKBENCH_LEGACY_PATH="${USER_HOME_LOCAL_BIN}/terra"

readonly WORKBENCH_GIT_REPOS_DIR="${USER_HOME_DIR}/repos"

readonly WORKBENCH_BOOT_SCRIPT="${USER_WORKBENCH_CONFIG_DIR}/instance-boot.sh"
readonly WORKBENCH_BOOT_SERVICE_NAME="workbench-instance-boot.service"
readonly WORKBENCH_BOOT_SERVICE="/etc/systemd/system/${WORKBENCH_BOOT_SERVICE_NAME}"

readonly WORKBENCH_SSH_AGENT_SCRIPT="${USER_WORKBENCH_CONFIG_DIR}/ssh-agent-start.sh"
readonly WORKBENCH_SSH_AGENT_SERVICE_NAME="workbench-ssh-agent.service"
readonly WORKBENCH_SSH_AGENT_SERVICE="/etc/systemd/system/${WORKBENCH_SSH_AGENT_SERVICE_NAME}"

# Variables for optional software frameworks
readonly HAIL_SCRIPT_PATH="${USER_WORKBENCH_CONFIG_DIR}/install-hail.py"

# Location of gitignore configuration file for users
readonly GIT_IGNORE="${USER_HOME_DIR}/gitignore_global"

# Move to the /tmp directory to let any artifacts left behind by this script can be removed.
cd /tmp || exit

# Send stdout and stderr from this script to a file for debugging.
# Make the .wb directory as the user so that they own it and have correct linux permissions.
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_WORKBENCH_CONFIG_DIR}'"
${RUN_AS_LOGIN_USER} "ln -sf '${USER_WORKBENCH_CONFIG_DIR}' '${USER_WORKBENCH_LEGACY_CONFIG_DIR}'"
exec >> "${POST_STARTUP_OUTPUT_FILE}"
exec 2>&1

#######################################
# Emit a message with a timestamp
#######################################
function emit() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

#######################################
# Retrieve a value from the GCE metadata server or return nothing.
# See https://cloud.google.com/compute/docs/storing-retrieving-metadata
# Arguments:
#   The metadata subpath to retrieve
# Returns:
#   The metadata value if found, or else an empty string
#######################################
function get_metadata_value() {
  local metadata_path="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata/computeMetadata/v1/${metadata_path}"
}

#######################################
# Set guest attributes on GCE. Used here to log completion status of the script.
# See https://cloud.google.com/compute/docs/metadata/manage-guest-attributes
# Arguments:
#   $1: The guest attribute domain and key IE startup_script/status
#   $2  The data to write to the guest attribute
#######################################
function set_guest_attributes() {
  local attr_path="${1}"
  local attr_value="${2}"
  curl -s -X PUT --data "${attr_value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${attr_path}"
}

# If the script exits without error let the UI know it completed successfully
# Otherwise if an error occurred write the line and command that failed to guest attributes.
function exit_handler {
  local exit_code="${1}"
  local line_no="${2}"
  local command="${3}"
  # Success! Set the guest attributes and exit cleanly
  if [[ "${exit_code}" -eq 0 ]]; then
    set_guest_attributes "${STATUS_ATTRIBUTE}" "COMPLETE"
    # Create a root permissioned file to indicate that the script has completed successfully in case of a reboot.
    touch "${STARTUP_SCRIPT_COMPLETE}"
    exit 0
  fi
  # Write error status and message to guest attributes
  set_guest_attributes "${STATUS_ATTRIBUTE}" "ERROR"
  set_guest_attributes "${MESSAGE_ATTRIBUTE}" "Error on line ${line_no}, command \"${command}\". See ${POST_STARTUP_OUTPUT_FILE} for more information."
  exit "${exit_code}"
}
trap 'exit_handler $? $LINENO $BASH_COMMAND' EXIT

#######################################
### Begin environment setup 
#######################################

# Let the UI know the script has started
set_guest_attributes "${STATUS_ATTRIBUTE}" "STARTED"

# Add login user to sudoers and enable sudo without password on it
emit "Adding login user to sudoers..."
readonly NO_PROMPT_SUDOERS_FILE="/etc/sudoers.d/no-sudo-password-prompt-${LOGIN_USER}"
usermod -aG sudo "${LOGIN_USER}"
echo "${LOGIN_USER} ALL=(ALL:ALL) NOPASSWD: ALL" > "${NO_PROMPT_SUDOERS_FILE}"

# Remove default user bashrc to ensure that the user's bashrc is sourced in non interactive shells
${RUN_AS_LOGIN_USER} "rm -f '${USER_BASHRC}'"
${RUN_AS_LOGIN_USER} "touch '${USER_BASHRC}'"

emit "Resynchronizing apt package index..."

# The apt package index may not be clean when we run; resynchronize
apt-get update

# Create the target directories for installing into the HOME directory
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_BIN}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"

# As described above, have the ~/.bash_profile source the ~/.bashrc
cat << EOF >> "${USER_BASH_PROFILE}"

### BEGIN: Workbench-specific customizations ###
if [[ -e ~/.bashrc ]]; then
  source ~/.bashrc
fi
### END: Workbench-specific customizations ###

EOF

# Indicate the start of Workbench customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

### BEGIN: Workbench-specific customizations ###

# Prepend "${USER_HOME_LOCAL_BIN}" (if not already in the path)
if [[ ":\${PATH}:" != *":${USER_HOME_LOCAL_BIN}:"* ]]; then
  export PATH="${USER_HOME_LOCAL_BIN}":"\${PATH}"
fi
EOF

emit "Installing common packages via pip..."

# Install common packages. Use pip instead of conda because conda is slow.
${RUN_AS_LOGIN_USER} "${RUN_PIP} install --user \
  dsub \
  nbdime \
  nbstripout \
  pandas_gbq \
  pre-commit \
  pylint \
  pytest"

# Install nbstripout for the jupyter user in all git repositories.
${RUN_AS_LOGIN_USER} "nbstripout --install --global"

# Installs gcsfuse if it is not already installed.
if ! which gcsfuse >/dev/null 2>&1; then
  emit "Installing gcsfuse..."
  # install packages needed to install gcsfuse
  apt-get install -y \
    gnupg \
    lsb-release

  # Install based on gcloud docs here https://cloud.google.com/storage/docs/gcsfuse-install.
  export GCSFUSE_REPO="gcsfuse-$(lsb_release -c -s)" \
    && echo "deb https://packages.cloud.google.com/apt ${GCSFUSE_REPO} main" | tee /etc/apt/sources.list.d/gcsfuse.list \
    && curl "https://packages.cloud.google.com/apt/doc/apt-key.gpg" | apt-key add -
  apt-get update \
    && apt-get install -y gcsfuse
else
  emit "gcsfuse already installed. Skipping installation."
fi

# Set gcloud region config property to the region of the Dataproc cluster
readonly DATAPROC_REGION="$(get_metadata_value "instance/attributes/dataproc-region")"
${RUN_AS_LOGIN_USER} "gcloud config set dataproc/region ${DATAPROC_REGION}"

###########################################################
# The Workbench CLI requires Java 17 or higher
#
# Install using a TAR file as that allows for installing
# it into the Jupyter user HOME directory.
# Other forms of Java installation do a "system install".
#
# Note that this leaves the default VM Java alone
# (in /usr/bin/java).
#
# We pick up the right version by putting ~/.local/bin
# into the PATH.
#########################################################
emit "Installing Java JDK ..."

# Set up a known clean directory for downloading the TAR and unzipping it.
${RUN_AS_LOGIN_USER} "mkdir -p '${JAVA_INSTALL_TMP}'"
pushd "${JAVA_INSTALL_TMP}"

# Download the latest Java 17, untar it, and remove the TAR file
${RUN_AS_LOGIN_USER} "\
  curl -Os https://download.oracle.com/java/17/latest/jdk-17_linux-x64_bin.tar.gz && \
  tar xfz jdk-17_linux-x64_bin.tar.gz && \
  rm jdk-17_linux-x64_bin.tar.gz"

# Get the name local directory that was untarred (something like "jdk-17.0.7")
JAVA_DIRNAME="$(ls)"

# Move it to ~/.local
${RUN_AS_LOGIN_USER} "mv '${JAVA_DIRNAME}' '${USER_HOME_LOCAL_SHARE}'"

# Create a soft link in ~/.local/bin to the java runtime
ln -s "${USER_HOME_LOCAL_SHARE}/${JAVA_DIRNAME}/bin/java" "${USER_HOME_LOCAL_BIN}"
chown --no-dereference "${LOGIN_USER}:${LOGIN_USER}" "${USER_HOME_LOCAL_BIN}/java"

# Clean up
popd
rmdir "${JAVA_INSTALL_TMP}"

# Download Nextflow and install it
emit "Installing Nextflow ..."

${RUN_AS_LOGIN_USER} "\
  curl -s https://get.nextflow.io | bash && \
  mv nextflow '${NEXTFLOW_INSTALL_PATH}'"

# Download Cromwell and install it
emit "Installing Cromwell ..."

${RUN_AS_LOGIN_USER} "\
  curl -LO 'https://github.com/broadinstitute/cromwell/releases/download/${CROMWELL_LATEST_VERSION}/cromwell-${CROMWELL_LATEST_VERSION}.jar' && \
  mkdir -p '${CROMWELL_INSTALL_DIR}' && \
  mv 'cromwell-${CROMWELL_LATEST_VERSION}.jar' '${CROMWELL_INSTALL_DIR}'"

# Set a variable for the user in the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

# Set a convenience variable pointing to the version-specific Cromwell JAR file
export CROMWELL_JAR="${CROMWELL_INSTALL_JAR}"
EOF

# Download cromshell and install it
emit "Installing Cromshell ..."

apt-get -y install mailutils
${RUN_AS_LOGIN_USER} "\
  curl -Os https://raw.githubusercontent.com/broadinstitute/cromshell/master/cromshell && \
  chmod +x cromshell && \
  mv cromshell '${CROMSHELL_INSTALL_PATH}'"

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

# Set variables into the ~/.bashrc such that they are available
# to terminals, notebooks, and other tools
#
# We have new-style variables (eg GOOGLE_CLOUD_PROJECT) which are set here
# and CLI (wb app execute env).
# We also support a few variables set by Leonardo (eg GOOGLE_PROJECT).
# Those are only set here and NOT in the CLI as they are intended just
# to make porting existing notebooks easier.

# Keep in sync with the CLI environment variables:
# https://github.com/verily-src/terra-tool-cli/blob/6c3d1ee2dd54aa62785da4113b83f5eba57d3c7f/src/main/java/bio/terra/cli/app/CommandRunner.java#L89

# *** Variables that are set by Leonardo for Cloud Environments
# (https://github.com/DataBiosphere/leonardo)

# OWNER_EMAIL is really the Workbench user account email address
readonly OWNER_EMAIL="$(
  ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
  jq --raw-output ".userEmail")"

# GOOGLE_PROJECT is the project id for the GCP project backing the workspace
readonly GOOGLE_PROJECT="$(
  ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
  jq --raw-output ".googleProjectId")"

# PET_SA_EMAIL is the pet service account for the Workbench user and
# is specific to the GCP project backing the workspace
readonly PET_SA_EMAIL="$(
  ${RUN_AS_LOGIN_USER} "wb auth status --format=json" | \
  jq --raw-output ".serviceAccountEmail")"

# These are equivalent environment variables which are set for a
# command when calling "wb app execute <command>".
#
# WORKBENCH_USER_EMAIL is the Workbench user account email address.
# GOOGLE_CLOUD_PROJECT is the project id for the GCP project backing the
# workspace.
# GOOGLE_SERVICE_ACCOUNT_EMAIL is the pet service account for the Workbench user
# and is specific to the GCP project backing the workspace.

emit "Adding Workbench environment variables to ~/.bashrc ..."

cat << EOF >> "${USER_BASHRC}"

# Set up a few legacy Workbench-specific convenience variables
export OWNER_EMAIL='${OWNER_EMAIL}'
export GOOGLE_PROJECT='${GOOGLE_PROJECT}'
export PET_SA_EMAIL='${PET_SA_EMAIL}'

# Set up a few Workbench-specific convenience variables
export WORKBENCH_USER_EMAIL='${OWNER_EMAIL}'
export GOOGLE_CLOUD_PROJECT='${GOOGLE_PROJECT}'
export GOOGLE_SERVICE_ACCOUNT_EMAIL='${PET_SA_EMAIL}'
EOF

#############################
# Configure Workbench CLI Wrapper
#############################
# Create a wrapper script that sets $JAVA_HOME and then executes the 'wb' command.

# Move the installed 'wb' binary to a new location
mv "${WORKBENCH_WRAPPER_PATH}" "${WORKBENCH_COMMAND_PATH}"

# Create the wrapper script
cat << EOF >> "${WORKBENCH_WRAPPER_PATH}"
#!/bin/bash

# Set JAVA_HOME before calling the Workbench cli
export JAVA_HOME="${USER_HOME_LOCAL_DIR}"

# Execute Workbench
"${WORKBENCH_COMMAND_PATH}" "\$@"

EOF

# Make sure the wrapper script is executable by the login user
chmod +x "${WORKBENCH_WRAPPER_PATH}"
chown "${LOGIN_USER}:${LOGIN_USER}" "${WORKBENCH_WRAPPER_PATH}"

# Copy 'wb' to its legacy 'terra' name.
cp "${WORKBENCH_WRAPPER_PATH}" "${WORKBENCH_LEGACY_PATH}"


#################
# bash completion
#################
#
# bash_completion is installed on Vertex AI notebooks, but the installed
# completion scripts are *not* sourced from /etc/profile.
# If we need it system-wide, we can install it there, but otherwise, let's
# keep changes localized to the LOGIN_USER.
#
emit "Configuring bash completion for the VM..."

cat << 'EOF' >> "${USER_BASHRC}"

# Source available global bash tab completion scripts
if [[ -d /etc/bash_completion.d ]]; then
  for BASH_COMPLETION_SCRIPT in /etc/bash_completion.d/* ; do
    source "${BASH_COMPLETION_SCRIPT}"
  done
fi

# Source available user installed bash tab completion scripts
if [[ -d ~/.bash_completion.d ]]; then
  for BASH_COMPLETION_SCRIPT in ~/.bash_completion.d/* ; do
    source "${BASH_COMPLETION_SCRIPT}"
  done
fi
EOF

###############
# git setup
###############

emit "Setting up git integration..."

# Create the user SSH directory 
${RUN_AS_LOGIN_USER} "mkdir -p ${USER_SSH_DIR} --mode 0700"

# Get the user's SSH key from Workbench, and if set, write it to the user's .ssh directory
${RUN_AS_LOGIN_USER} "\
  install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa.tmp' && \
  wb security ssh-key get --include-private-key --format=JSON >> '${USER_SSH_DIR}/id_rsa.tmp' || true"
if [[ -s "${USER_SSH_DIR}/id_rsa.tmp" ]]; then
  ${RUN_AS_LOGIN_USER} "\
    install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa' && \
    jq -r '.privateSshKey' '${USER_SSH_DIR}/id_rsa.tmp' > '${USER_SSH_DIR}/id_rsa'"
fi
rm -f "${USER_SSH_DIR}/id_rsa.tmp"

# Set the github known_hosts
${RUN_AS_LOGIN_USER} "ssh-keyscan -H github.com >> '${USER_SSH_DIR}/known_hosts'"

# Create git repos directory
${RUN_AS_LOGIN_USER} "mkdir -p '${WORKBENCH_GIT_REPOS_DIR}'"

# Attempt to clone all the git repo references in the workspace. If the user's ssh key does not exist or doesn't have access
# to the git references, the corresponding git repo cloning will be skipped.
# Keep this as last thing in script. There will be integration test for git cloning (PF-1660). If this is last thing, then
# integration test will ensure that everything in script worked.
${RUN_AS_LOGIN_USER} "cd '${WORKBENCH_GIT_REPOS_DIR}' && wb git clone --all"

# Setup gitignore to avoid accidental checkin of data.

cat << EOF | sudo --preserve-env -u "${LOGIN_USER}" tee "${GIT_IGNORE}"
# By default, all files should be ignored by git.
# We want to be sure to exclude files containing data such as CSVs and images such as PNGs.
*.*
# Now, allow the file types that we do want to track via source control.
!*.ipynb
!*.py
!*.r
!*.R
!*.wdl
!*.sh
# Allow documentation files.
!*.md
!*.rst
!LICENSE*
EOF

${RUN_AS_LOGIN_USER} "git config --global core.excludesfile '${GIT_IGNORE}'"

# Create a script for starting the ssh-agent, which will be run as a daemon
# process on boot.
#
# The ssh-agent information is deposited into the jupyter user's HOME directory
# (under ~/.ssh-agent), including the socket file and the environment variables
# that clients need.
#
# Writing to the HOME directory allows for the ssh-agent socket to be accessible
# from inside Docker containers that have mounted the Jupyter user's HOME directory.

cat << 'EOF' >>"${WORKBENCH_SSH_AGENT_SCRIPT}"
#!/bin/bash

set -o nounset

mkdir -p ~/.ssh-agent

readonly SOCKET_FILE=~/.ssh-agent/ssh-socket
readonly ENVIRONMENT_FILE=~/.ssh-agent/environment

# Start a new ssh-agent if one is not already running.
# If the ssh-agent is already running, but we don't have the environment
# variables (SSH_AUTH_SOCK and SSH_AGENT_PID), then we look for them in
# a file ~/.ssh-agent/environment.
#
# If we can't connect to the ssh-agent, it'll return ENOENT (no entity).
ssh-add -l &>/dev/null
if [[ "$?" == 2 ]]; then
  # If a .ssh-agent/environment file already exists, then it has the environment
  # variables we need: SSH_AUTH_SOCK and SSH_AGENT_PID
  if [[ -e "${ENVIRONMENT_FILE}" ]]; then
    eval "$(<"${ENVIRONMENT_FILE}")" >/dev/null
  fi

  # Try again to connect to the agent to list keys
  ssh-add -l &>/dev/null
  if [[ "$?" == 2 ]]; then
    # Start the ssh-agent, writing connection variables to ~/.ssh-agent
    rm -f "${SOCKET_FILE}"
    (umask 066; ssh-agent -a "${SOCKET_FILE}" > "${ENVIRONMENT_FILE}")

    # Set the variables in the environment
    eval "$(<"${ENVIRONMENT_FILE}")" >/dev/null
  fi
fi

# Add ssh keys (if any)
ssh-add -q

# This script is intended to be run as a daemon process.
# Block until the ssh-agent goes away.
while [[ -e /proc/"${SSH_AGENT_PID}" ]]; do
  sleep 10s
done
echo "SSH agent ${SSH_AGENT_PID} has exited."
EOF
chmod +x "${WORKBENCH_SSH_AGENT_SCRIPT}"
chown "${LOGIN_USER}:${LOGIN_USER}" "${WORKBENCH_SSH_AGENT_SCRIPT}"

# Create a systemd service file for the ssh-agent
cat << EOF >"${WORKBENCH_SSH_AGENT_SERVICE}"
[Unit]
Description=Run an SSH agent for the Jupyter user

[Service]
ExecStart=${WORKBENCH_SSH_AGENT_SCRIPT}
User=${LOGIN_USER}
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the startup service
systemctl daemon-reload
systemctl enable "${WORKBENCH_SSH_AGENT_SERVICE_NAME}"
systemctl start "${WORKBENCH_SSH_AGENT_SERVICE_NAME}"

# Set ssh-agent launch command in ~/.bashrc so everytime
# user starts a shell, we start the ssh-agent.
cat << EOF >> "${USER_BASHRC}"

# Get the ssh-agent environment variables
if [[ -f ~/.ssh-agent/environment ]]; then
  eval "\$(<~/.ssh-agent/environment)" >/dev/null
fi
EOF

#############################
# Setup instance boot service
#############################
# Create a script to perform the following steps every time the instance boots:
# 1. Mount Workbench workspace resources. This command requires system user home
#    directories to be mounted. We run the startup service after
#    jupyter.service to meet this requirement.

emit "Setting up Workbench boot script and service..."

# Create the boot script
cat << EOF >"${WORKBENCH_BOOT_SCRIPT}"
#!/bin/bash
# This script is run on instance boot to configure the instance for Workbench.

# Send stdout and stderr from this script to a file for debugging.
exec >> "${WORKBENCH_BOOT_SERVICE_OUTPUT_FILE}"
exec 2>&1

# Pick up environment from the ~/.bashrc
source "${USER_BASHRC}"

# Mount Workbench workspace resources
"${USER_HOME_LOCAL_BIN}/wb" resource mount

exit 0
EOF
chmod +x "${WORKBENCH_BOOT_SCRIPT}"
chown "${LOGIN_USER}:${LOGIN_USER}" "${WORKBENCH_BOOT_SCRIPT}"

# Create a systemd service to run the boot script on system boot
cat << EOF >"${WORKBENCH_BOOT_SERVICE}"
[Unit]
Description=Configure environment for Workbench
After=jupyter.service

[Service]
ExecStart=${WORKBENCH_BOOT_SCRIPT}
User=${LOGIN_USER}
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable "${WORKBENCH_BOOT_SERVICE_NAME}"
systemctl start "${WORKBENCH_BOOT_SERVICE_NAME}"

# Indicate the end of Workbench customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

### END: Workbench-specific customizations ###
EOF

# Make sure the ~/.bashrc and ~/.bash_profile are owned by the jupyter user
chown "${LOGIN_USER}:${LOGIN_USER}" "${USER_BASHRC}"
chown "${LOGIN_USER}:${LOGIN_USER}" "${USER_BASH_PROFILE}"


###################################
# Start workbench app proxy agent 
###################################

readonly APP_PROXY=$(get_metadata_value "instance/attributes/terra-app-proxy")
if [[ -n "${APP_PROXY}" ]]; then
  emit "Using custom Proxy Agent"
  RESOURCE_ID=$(get_metadata_value "instance/attributes/terra-resource-id")
  NEW_PROXY="https://${APP_PROXY}"
  NEW_PROXY_URL="${RESOURCE_ID}.${APP_PROXY}"

  # Create a systemd service to start the workbench app proxy.
  cat << EOF > "${WORKBENCH_PROXY_AGENT_SERVICE}"
[Unit]
Description=Workbench App Proxy Agent Service

[Service]
ExecStart=/bin/bash -c '/usr/bin/proxy-forwarding-agent -proxy ${NEW_PROXY}/ -host localhost:8123 -backend ${RESOURCE_ID} -shim-path websocket-shim -banner-height=40px -inject-banner="\$(cat /opt/dataproc/proxy-agent/banner.html)"  -session-cookie-name=_xsrf'
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

  # Enable and start the workbench app proxy agent service
  systemctl daemon-reload
  systemctl enable "${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"
  systemctl start "${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"
  emit "Workbench proxy Agent service started"
fi

###################################
# Configure Jupyter systemd service
###################################

# By default the Dataproc jupyter optional component runs jupyter as the root user.
# We override the behavior by configuring the jupyter service to run as the login user instead.

emit "Configuring Jupyter systemd service..."

# Modify the jupyter service configuration
cat << EOF >${JUPYTER_SERVICE}
[Unit]
Description=Jupyter Notebook Server
After=hadoop-yarn-resourcemanager.service

[Service]
Type=simple
User=${LOGIN_USER}
Group=${LOGIN_USER}
EnvironmentFile=/etc/environment
EnvironmentFile=/etc/default/jupyter
WorkingDirectory=${USER_HOME_DIR}
ExecStart=/bin/bash --login -c '/opt/conda/miniconda3/bin/jupyter notebook &>> ${USER_HOME_DIR}/jupyter_notebook.log'
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

############################
# Install Software Framework
############################

# If the script executer has set the "software-framework" property to "HAIL",
# then install Hail after Dataproc optional components are installed.

readonly SOFTWARE_FRAMEWORK="$(get_metadata_value "instance/attributes/software-framework")"

if [[ "${SOFTWARE_FRAMEWORK}" == "HAIL" ]]; then
  emit "Installing Hail..."

  # Create the Hail install script. The script is based off of Hail's init_notebook.py
  # script that is executed by 'hailctl dataproc start'. This modified script omits
  # the following steps:
  # - Configuring and starting a custom jupyter systemd service
  # - Configuring and enabling hail's spark monitor nbextension.
  # TODO: BENCH-1094: Consider whether we need spark monitor
  cat << EOF >"${HAIL_SCRIPT_PATH}"
#!${RUN_PYTHON}
# This modified Hail installation script installs the necessary Hail packages and jupyter extensions,
# but does not install jupyter or set up a jupyter service as it already handled by the Dataproc jupyter optional component.
# See: https://storage.googleapis.com/hail-common/hailctl/dataproc/0.2.120/init_notebook.py
# Note that we intentionally did not make any updates to this script for style
# such that it easier to track changes.
import json
import os
import subprocess as sp
import sys
from subprocess import check_output

assert sys.version_info > (3, 0), sys.version_info

if sys.version_info >= (3, 7):
    def safe_call(*args, **kwargs):
        sp.run(args, capture_output=True, check=True, **kwargs)
else:
    def safe_call(*args, **kwargs):
        try:
            sp.check_output(args, stderr=sp.STDOUT, **kwargs)
        except sp.CalledProcessError as e:
            print(e.output).decode()
            raise e


def get_metadata(key):
    return check_output(['/usr/share/google/get_metadata_value', 'attributes/{}'.format(key)]).decode()

def mkdir_if_not_exists(path):
    os.makedirs(path, exist_ok=True)


# additional packages to install
pip_pkgs = [
    'setuptools',
    'mkl<2020',
    'lxml<5'
]

# add user-requested packages
try:
    user_pkgs = get_metadata('PKGS')
except Exception:
    pass
else:
    pip_pkgs.extend(user_pkgs.split('|'))

print('pip packages are {}'.format(pip_pkgs))
command = ['${RUN_PIP}', 'install']
command.extend(pip_pkgs)
safe_call(*command)

print('getting metadata')

wheel_path = get_metadata('WHEEL')
wheel_name = wheel_path.split('/')[-1]

print('copying wheel')
safe_call('gsutil', 'cp', wheel_path, f'/home/hail/{wheel_name}')

safe_call('${RUN_PIP}', 'install', '--no-dependencies', f'/home/hail/{wheel_name}')

print('setting environment')

spark_lib_base = '/usr/lib/spark/python/lib/'
files_to_add = [os.path.join(spark_lib_base, x) for x in os.listdir(spark_lib_base) if x.endswith('.zip')]

env_to_set = {
    'PYTHONHASHSEED': '0',
    'PYTHONPATH': ':'.join(files_to_add),
    'SPARK_HOME': '/usr/lib/spark/',
    'PYSPARK_PYTHON': '${RUN_PYTHON}',
    'PYSPARK_DRIVER_PYTHON': '${RUN_PYTHON}',
}

print('setting environment')

for e, value in env_to_set.items():
    safe_call('/bin/sh', '-c',
              'set -ex; echo "export {}={}" | tee -a /etc/environment /usr/lib/spark/conf/spark-env.sh'.format(e, value))

hail_jar = sp.check_output([
    '/bin/sh', '-c',
    'set -ex; ${RUN_PYTHON} -m pip show hail | grep Location | sed "s/Location: //"'
]).decode('ascii').strip() + '/hail/backend/hail-all-spark.jar'

conf_to_set = [
    'spark.executorEnv.PYTHONHASHSEED=0',
    'spark.app.name=Hail',
    # the below are necessary to make 'submit' work
    'spark.jars={}'.format(hail_jar),
    'spark.driver.extraClassPath={}'.format(hail_jar),
    'spark.executor.extraClassPath=./hail-all-spark.jar',
]

print('setting spark-defaults.conf')

with open('/etc/spark/conf/spark-defaults.conf', 'a') as out:
    out.write('\n')
    for c in conf_to_set:
        out.write(c)
        out.write('\n')

# create Jupyter kernel spec file
kernel = {
    'argv': [
        '${RUN_PYTHON}',
        '-m',
        'ipykernel',
        '-f',
        '{connection_file}'
    ],
    'display_name': 'Hail',
    'language': 'python',
    'env': {
        **env_to_set,
# REMOVED SPARK MONITOR ENVS
    }
}

# write kernel spec file to default Jupyter kernel directory
mkdir_if_not_exists('/opt/conda/default/share/jupyter/kernels/hail/')
with open('/opt/conda/default/share/jupyter/kernels/hail/kernel.json', 'w') as f:
    json.dump(kernel, f)

# REMOVED SPARK MONITOR INSTALLATION

# setup jupyter-spark extension
safe_call('${RUN_JUPYTER}', 'nbextension', 'enable', '--user', '--py', 'widgetsnbextension')

print("hail installed successfully.")

EOF
fi

# Fork the following into background process to execute after Dataproc finishes
# setting up its optional components.
#
# Post Dataproc setup tasks:
# 1. Wait for the Dataproc jupyter optional component to finish setting up.
# 2. Install Hail if it has been enabled.
# 3. Configure proxy agent banner and restart proxy agent.
# 4. Configure jupyter service config
#    a. Remove Dataproc's GCSContentsManager as we support bucket mounts in local file system.
#    b. Set jupyter file tree's root directory to the LOGIN_USER's home directory.
# 5. Restart jupyter service

"$(
  while ! systemctl is-active --quiet ${JUPYTER_SERVICE_NAME}; do
    sleep 5
    emit "Waiting for ${JUPYTER_SERVICE_NAME} to start..."
  done

  # Execute software specific post startup customizations
  if [[ "${SOFTWARE_FRAMEWORK}" == "HAIL" ]]; then
    emit "Starting Hail install script..."
    ${RUN_PYTHON} ${HAIL_SCRIPT_PATH}
  fi

  #################################
  # Configure Proxy Agent Overrides
  #################################

  # Map the CLI server to the appropriate UI url
  if [[ "${TERRA_SERVER}" == *"verily"* ]]; then
    # Map the CLI server to the appropriate UI url
    if [[ "${TERRA_SERVER}" == "verily" ]]; then
      ui_base_url="workbench.verily.com"
    else
      ui_base_url="${TERRA_SERVER/verily/terra}-ui-terra.api.verily.com"
    fi
  else
    >&2 echo "ERROR: ${TERRA_SERVER} is not a known verily server."
    exit 1
  fi

  # The banner.html file contains <style> wrapper tags and a series of CSS styles, and a set of html link elements that we want to modify.
  # Begin banner.html modifications

  # Insert a workspace link into the banner title
  readonly WORKSPACE_LINK_EL='<a id="workspace" class="forum" target="_blank" href="https://'"${ui_base_url}/workspaces/${TERRA_WORKSPACE}"'"'">${TERRA_WORKSPACE}</a>"
  sed -i 's#<banner-title>#<banner-title>\n'"${WORKSPACE_LINK_EL}"' \&gt; #' "${PROXY_AGENT_BANNER}"

  # Add target blank property to all banner links so they open in a new tab
  sed -i 's#class="forum"#class="forum" target="_blank"#g' "${PROXY_AGENT_BANNER}"

  # Remove flex styling from the banner-account css class to prevent banner content from wrapping
  sed -i '#banner-account {#,#}#{#flex:#d;#-ms-flex:#d;#-webkit-flex:#d;}' "${PROXY_AGENT_BANNER}"

  # Add css class for a#workspace before a#project
  sed -i '/a#project {/i\
a#workspace {\
  color:white;\
  text-decoration:none;\
  padding:4px;\
}' "${PROXY_AGENT_BANNER}"

  # End banner.html modifications

  # restart proxy agent
  systemctl restart "${PROXY_AGENT_SERVICE}"

  ###########################
  # Configure Jupyter service
  ###########################

  emit "Configuring Jupyter service..."
  # Add a marker for the Workbench-specific customizations
  cat << EOF >> "${JUPYTER_CONFIG}"

### BEGIN: Workbench-specific customizations ###

EOF

  # Remove the default GCSContentsManager and set jupyter file tree's root directory to the LOGIN_USER's home directory.
  sed -i -e "/c.GCSContentsManager/d" -e "/CombinedContentsManager/d" "${JUPYTER_CONFIG}"
  echo "c.FileContentsManager.root_dir = '${USER_HOME_DIR}'" >> "${JUPYTER_CONFIG}"
  
  if [[ -n "${APP_PROXY}" ]]; then
    cat << EOF >> "${JUPYTER_CONFIG}"
c.NotebookApp.allow_origin_pat += "|(https?://)?(https://${NEW_PROXY_URL})"
c.NotebookApp.allow_remote_access= True
c.NotebookApp.local_hostnames.append('${APP_PROXY}')
EOF
  fi
  # Add a marker for the Workbench-specific customizations
  cat << EOF >> "${JUPYTER_CONFIG}"

### END: Workbench-specific customizations ###

EOF

  # Restart jupyter to load configurations
  systemctl restart ${JUPYTER_SERVICE_NAME}
)" &

# reload systemctl daemon to load the updated jupyter configuration
systemctl daemon-reload

# The jupyter service will be restarted by the default Dataproc startup script
# and pick up the modified service configuration and environment variables.

####################################################################################
# Run a set of tests that should be invariant to the workspace or user configuration
####################################################################################

# Test java (existence and version)

emit "--  Checking if installed Java version is ${REQ_JAVA_VERSION} or higher"

# Get the current major version of Java: "11.0.12" => "11"
readonly INSTALLED_JAVA_VERSION="$(${RUN_AS_LOGIN_USER} "${JAVA_INSTALL_PATH} -version" 2>&1 | awk -F\" '{ split($2,a,"."); print a[1]}')"
if [[ "${INSTALLED_JAVA_VERSION}" -lt "${REQ_JAVA_VERSION}" ]]; then
  >&2 emit "ERROR: Java version detected (${INSTALLED_JAVA_VERSION}) is less than required (${REQ_JAVA_VERSION})"
  exit 1
fi

emit "SUCCESS: Java installed and version detected as ${INSTALLED_JAVA_VERSION}"

# Test nextflow
emit "--  Checking if Nextflow is properly installed"

readonly INSTALLED_NEXTFLOW_VERSION="$(${RUN_AS_LOGIN_USER} "${NEXTFLOW_INSTALL_PATH} -v" | sed -e 's#nextflow version \(.*\)#\1#')"

emit "SUCCESS: Nextflow installed and version detected as ${INSTALLED_NEXTFLOW_VERSION}"

# Test Cromwell
emit "--  Checking if installed Cromwell version is ${CROMWELL_LATEST_VERSION}"

readonly INSTALLED_CROMWELL_VERSION="$(${RUN_AS_LOGIN_USER} "java -jar ${CROMWELL_INSTALL_JAR} --version" | sed -e 's#cromwell \(.*\)#\1#')"
if [[ "${INSTALLED_CROMWELL_VERSION}" -ne ${CROMWELL_LATEST_VERSION} ]]; then
  >&2 emit "ERROR: Cromwell version detected (${INSTALLED_CROMWELL_VERSION}) is not equal to expected (${CROMWELL_LATEST_VERSION})"
  exit 1
fi

emit "SUCCESS: Cromwell installed and version detected as ${INSTALLED_CROMWELL_VERSION}"

# Test Cromshell
emit "--  Checking if Cromshell is properly installed"

if [[ ! -e "${CROMSHELL_INSTALL_PATH}" ]]; then
  >&2 emit "ERROR: Cromshell not found at ${CROMSHELL_INSTALL_PATH}"
  exit 1
fi
if [[ ! -x "${CROMSHELL_INSTALL_PATH}" ]]; then
  >&2 emit "ERROR: Cromshell not executable at ${CROMSHELL_INSTALL_PATH}"
  exit 1
fi

emit "SUCCESS: Cromshell installed"

# Test Workbench
emit "--  Checking if Workbench CLI is properly installed"

if [[ ! -e "${WORKBENCH_INSTALL_PATH}" ]]; then
  >&2 emit "ERROR: Workbench CLI not found at ${WORKBENCH_INSTALL_PATH}"
  exit 1
fi

readonly INSTALLED_WORKBENCH_VERSION="$(${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} version")"

if [[ -z "${INSTALLED_WORKBENCH_VERSION}" ]]; then
  >&2 emit "ERROR: Workbench CLI did not execute or did not return a version number"
  exit 1
fi

emit "--  Checking if the original Workbench CLI has been renamed to wb_cli"

if [[ ! -e "${WORKBENCH_COMMAND_PATH}" ]]; then
  >&2 emit "ERROR: Workbench CLI was not renamed to ${WORKBENCH_COMMAND_PATH}"
  exit 1
fi

emit "--  Checking if the Workbench CLI wrapper is properly created"

if [[ ! -e "${WORKBENCH_WRAPPER_PATH}" ]]; then
  >&2 emit "ERROR: Workbench CLI wrapper does not exist ${WORKBENCH_WRAPPER_PATH}"
  exit 1
fi


emit "SUCCESS: Workbench CLI installed and version detected as ${INSTALLED_WORKBENCH_VERSION}"

# SSH
emit "--  Checking if .ssh directory is properly set up"

if [[ ! -e "${USER_SSH_DIR}" ]]; then
  >&2 emit "ERROR: user SSH directory does not exist"
  exit 1
fi
readonly SSH_DIR_MODE="$(stat -c "%a %G %U" "${USER_SSH_DIR}")"
if [[ "${SSH_DIR_MODE}" != "700 dataproc dataproc" ]]; then
  >&2 emit "ERROR: user SSH directory permissions are incorrect: ${SSH_DIR_MODE}"
  exit 1
fi

# If the user didn't have an SSH key configured, then the id_rsa file won't exist.
# If they do have the file, check the permissions
if [[ -e "${USER_SSH_DIR}/id_rsa" ]]; then
  readonly SSH_KEY_FILE_MODE="$(stat -c "%a %G %U" "${USER_SSH_DIR}/id_rsa")"
  if [[ "${SSH_KEY_FILE_MODE}" != "600 dataproc dataproc" ]]; then
    >&2 emit "ERROR: user SSH key file permissions are incorrect: ${SSH_DIR_MODE}/id_rsa"
    exit 1
  fi
fi

# GIT_IGNORE
emit "--  Checking if gitignore is properly installed"

readonly INSTALLED_GITIGNORE="$(${RUN_AS_LOGIN_USER} "git config --global core.excludesfile")"

if [[ "${INSTALLED_GITIGNORE}" != "${GIT_IGNORE}" ]]; then
  >&2 emit "ERROR: gitignore not set up at ${GIT_IGNORE}"
  exit 1
fi

emit "SUCCESS: Gitignore installed at ${INSTALLED_GITIGNORE}"

# TODO: Pending CLI support in PF-2865 for setting cluster metadata for testing once we have CLI support.
