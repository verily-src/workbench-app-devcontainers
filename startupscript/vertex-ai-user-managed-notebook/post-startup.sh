#!/bin/bash
#
# Name: post-startup.sh
#
# NOTE FOR CONTRIBUTORS:
#   This startup script shares logic with the dataproc cluster here: service/src/main/java/bio/terra/workspace/service/resource/controlled/cloud/gcp/dataproccluster/startup.sh.
#   Please ensure that changes to shared logic are reflected in both scripts.
#
# Description
#   Default post startup script for Google Cloud Vertex AI Workbench VM
#   running JupyterLab.
#
# Metadata and guest attributes:
#   This script uses the following GCE metadata and guest attributes for startup orchestration:
#   - instance/guest-attributes/startup_script/status: Set by this script, storing the status of this script's execution. Possible values are "RUNNING", "COMPLETE", or "ERROR".
#   - instance/guest-attributes/startup_script/message: Set by this script, storing the message of this script's execution. If the status is "ERROR", this message will contain an error message, otherwise it will be empty.
#   - instance/attributes/terra-cli-server: Read by this script to configure the Workbench CLI server.
#   - instance/attributes/terra-workspace-id: Read by this script to configure the Workbench CLI workspace.
#   - instance/attributes/terra-app-proxy: app proxy url to configure proxy.
#   - instance/attributes/terra-resource-id: read by this script to retrieve the sam resource id of this VM instance.
#   - instance/attributes/terra-user-startup-script: Read by this script to optionally run a user-provided startup script.
#
# Execution details
#   The post-startup script runs on Vertex AI notebook VMs during *instance creation*;
#   it is not run on every instance start.
#
#   *** The post-startup script runs as root. ***
#
#   The startup script is executed from /opt/c2d/scripts/97-run-post-startup-script.sh
#   which will:
#     1- Get the GCS path from VM metadata (instance/attributes/post-startup-script)
#     2- Download it to /opt/c2d/post_start.sh
#     3- Execute /opt/c2d/post_start.sh
#     4- Set the VM guest attribute "notebooks/handle_post_startup_script" to "DONE".
#        Note that this attribute is set to DONE whether the script runs successfully or not.
#
#   The startup script will execute a user provided startup script defined in
#   the `terra-user-startup-script` instance metadata attribute. Non zero error
#   codes from the user startup script will cause this script to fail, and the
#   user is expected to debug failures via the output log in ~/.workbench/user-startup-output.txt
#
# How to test changes to this file:
#   Copy this file to a GCS bucket:
#   - gsutil cp vertex-ai-user-managed-notebook/post-startup.sh gs://MYBUCKET
#
#   Create a new VM (JupyterLab provided by JupyterLab service):
#   - wb resource create gcp-notebook \
#       --name="test_post_startup" \
#       --post-startup-script=gs://MYBUCKET/post-startup.sh
#
#   Create a new VM (JupyterLab provided by Docker image):
#   - wb resource create gcp-notebook \
#       --name="test_post_startup" \
#       --container-repository gcr.io/deeplearning-platform-release/pytorch-gpu \
#       --post-startup-script=gs://MYBUCKET/post-startup.sh
#
#   To test a new command in this script, be sure to run with "sudo" in a JupyterLab Terminal.
#
# Integration Tests
#   Please also make sure integration test `PrivateControlledAiNotebookInstancePostStartup` passes. Refer to
#   https://github.com/DataBiosphere/terra-workspace-manager/tree/main/integration#Run-nightly-only-test-suite-locally
#   for instruction on how to run the test.
#

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# The non-root linux user that JupyterLab will be running as. It's important to do some parts of setup in the
# user space, such as setting Workbench CLI settings which are persisted in the user's $HOME.
readonly LOGIN_USER="jupyter"

# Create an alias for cases when we need to run a shell command as the jupyter user.
# Note that we deliberately use "bash -l" instead of "sh" in order to get bash (instead of dash)
# and to pick up changes to the .bashrc.
#
# This is intentionally not a Bash function, as that can suppress error propagation.
# This is intentionally not a Bash alias as they are not supported in shell scripts.
readonly RUN_AS_LOGIN_USER="sudo -u ${LOGIN_USER} bash -l -c"

# Startup script status is propagated out to VM guest attributes
readonly STATUS_ATTRIBUTE="startup_script/status"
readonly MESSAGE_ATTRIBUTE="startup_script/message"

# As much as possible, install tools into ~/.local
# This allows for the same software to be installed whether JupyterLab is provided
# by the VM (jupyter service) or a Docker image (docker service).
# In the case of the Docker service, /home/jupyter is mounted into the container
# as /home/jupyter.

readonly USER_HOME_DIR="/home/${LOGIN_USER}"
readonly USER_BASH_COMPLETION_DIR="${USER_HOME_DIR}/.bash_completion.d"
readonly USER_HOME_LOCAL_BIN="${USER_HOME_DIR}/.local/bin"
readonly USER_HOME_LOCAL_SHARE="${USER_HOME_DIR}/.local/share"
readonly USER_WORKBENCH_CONFIG_DIR="${USER_HOME_DIR}/.workbench"
readonly USER_WORKBENCH_LEGACY_CONFIG_DIR="${USER_HOME_DIR}/.terra"
readonly USER_SSH_DIR="${USER_HOME_DIR}/.ssh"

# When a user opens a Terminal in JupyerLab, documented behavior
# (https://github.com/jupyterlab/jupyterlab/issues/1733) is to create
# an interactive non-login shell, which sources the ~/.bashrc.
#
# This is the behavior observed when JupyterLab is provided by a Docker image
# from a DeepLearning Docker image.
# However JupyterLab Terminals on Vertex AI Workbench instances (non Dockerized)
# open a login shell, which sources the ~/.bash_profile.
#
# For consistency across these two environments, this startup script writes 
# to the ~/.bashrc, and has the ~/.bash_profile source the ~/.bashrc
readonly USER_BASHRC="${USER_HOME_DIR}/.bashrc"
readonly USER_BASH_PROFILE="${USER_HOME_DIR}/.bash_profile"

readonly POST_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/post-startup-output.txt"
readonly USER_STARTUP_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/user-startup-output.txt"
readonly WORKBENCH_BOOT_SERVICE_OUTPUT_FILE="${USER_WORKBENCH_CONFIG_DIR}/boot-output.txt"

# Variables relevant for 3rd party software that gets installed
readonly REQ_JAVA_VERSION=17
readonly JAVA_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/java"
readonly JAVA_INSTALL_TMP="${USER_WORKBENCH_CONFIG_DIR}/javatmp"

readonly NEXTFLOW_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/nextflow"

readonly CROMWELL_LATEST_VERSION=81
readonly CROMWELL_INSTALL_DIR="${USER_HOME_LOCAL_SHARE}/java"
readonly CROMWELL_INSTALL_JAR="${CROMWELL_INSTALL_DIR}/cromwell-${CROMWELL_LATEST_VERSION}.jar"

readonly CROMSHELL_INSTALL_PATH="${USER_HOME_LOCAL_BIN}/cromshell"

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

readonly WORKBENCH_PROXY_AGENT_SERVICE_NAME="workbench-proxy-agent.service"
readonly WORKBENCH_PROXY_AGENT_SERVICE="/etc/systemd/system/${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"

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
  curl --retry 5 -s -f \
      -H "Metadata-Flavor: Google" \
      "http://metadata/computeMetadata/v1/$1" \
    || echo -n
}
readonly -f get_metadata_value

#######################################
# function to retry command
#######################################
function retry () {
  local max_attempts="$1"
  local command="$2"

  local attempt
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    # Run the command and return if success
    if ${command}; then
      return
    fi

    # Sleep a bit in case the problem is a transient network/server issue
    if ((attempt < max_attempts)); then
      echo "Retrying $(command) in 5 seconds"
      sleep 5
    fi
  done

  # Execute without the if/then protection such that the exit code propagates
  ${command}
}
readonly -f retry

#################################
# Download and install Nextflow
#################################
function install_nextflow() {
  ${RUN_AS_LOGIN_USER} "curl -s https://get.nextflow.io | bash"
}
readonly -f install_nextflow
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
readonly -f set_guest_attributes

# Map the CLI server to appropriate service path
function get_service_url() {
  case "$1" in
    "verily") echo "https://workbench.verily.com/api/$2" ;;
    "dev-stable") echo "https://workbench-dev.verily.com/api/$2" ;;
    "dev-unstable") echo "https://workbench-dev-unstable.verily.com/api/$2" ;;
    "test") echo "https://workbench-test.verily.com/api/$2" ;;
    "staging") echo "https://workbench-staging.verily.com/api/$2" ;;
    "prod") echo "https://workbench.verily.com/api/$2" ;;
    *) return 1 ;;
  esac
}
readonly -f get_service_url

# If the script exits without error let the UI know it completed successfully
# Otherwise if an error occurred write the line and command that failed to guest attributes.
function exit_handler {
  local exit_code="${1}"
  local line_no="${2}"
  local command="${3}"
  # Success! Set the guest attributes and exit cleanly
  if [[ "${exit_code}" -eq 0 ]]; then
    set_guest_attributes "${STATUS_ATTRIBUTE}" "COMPLETE"
    exit 0
  fi
  # Write error status and message to guest attributes
  set_guest_attributes "${STATUS_ATTRIBUTE}" "ERROR"
  set_guest_attributes "${MESSAGE_ATTRIBUTE}" "Error on line ${line_no}, command \"${command}\". See ${POST_STARTUP_OUTPUT_FILE} for more information."
  exit "${exit_code}"
}
readonly -f exit_handler
trap 'exit_handler $? $LINENO $BASH_COMMAND' EXIT

#######################################
### Begin environment setup 
#######################################

# Let the UI know the script has started
set_guest_attributes "${STATUS_ATTRIBUTE}" "STARTED"

emit "Determining JupyterLab environment (jupyter.service or docker)"

INSTANCE_CONTAINER="$(get_metadata_value "instance/attributes/container")"
readonly INSTANCE_CONTAINER
if [[ -n "${INSTANCE_CONTAINER}" ]]; then
  emit "Custom container for JupyterLab detected: ${INSTANCE_CONTAINER}."
  # When JupyterLab is provided by a Docker container, the default Deep Learning images
  # pick up jupyter_notebook_config.py provided by the host VM.
  # See https://jupyter-notebook.readthedocs.io/en/stable/config.html for details of
  # the notebook server options supported.
  NOTEBOOK_CONFIG="/opt/deeplearning/jupyter/jupyter_notebook_config.py"
else
  emit "Non-containerized JupyterLab detected."
  NOTEBOOK_CONFIG="${USER_HOME_DIR}/.jupyter/jupyter_notebook_config.py"
fi

readonly NOTEBOOK_CONFIG
emit "Resynchronizing apt package index..."

# TODO (BENCH-2316): Update apt to point to the new k8s pkg. https://kubernetes.io/blog/2023/08/15/pkgs-k8s-io-introduction/
# Remove this when deep learning image fix this issue.
mkdir /etc/apt/keyrings
chmod 755 /etc/apt/keyrings
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /" | tee /etc/apt/sources.list.d/kubernetes.list
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
# The apt package index may not be clean when we run; resynchronize
apt-get update --allow-releaseinfo-change

# Create the target directories for installing into the HOME directory
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_BIN}'"
${RUN_AS_LOGIN_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"

# Remove the Vertex AI-installed "tutorials" directory.
# End users think that they are Workbench tutorials which is just confusing.
emit "Removing the pre-installed Vertex AI tutorials directory"
rm -rf "${USER_HOME_DIR}/tutorials"

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

# Add a marker for the Workbench-specific customizations
cat << EOF >> "${NOTEBOOK_CONFIG}"

### BEGIN: Workbench-specific customizations ###

# Allow users to toggle display of hidden files in file browser
c.ContentsManager.allow_hidden = True

EOF

# Update the PATH for container JupyterLab
if [[ -n "${INSTANCE_CONTAINER}" ]]; then

  cat << EOF >> "${NOTEBOOK_CONFIG}"

import os

os.environ['PATH'] = "${USER_HOME_LOCAL_BIN}:" + os.environ['PATH']
EOF

fi

emit "Installing common packages via pip..."

# Install common packages. Use pip instead of conda because conda is slow.
${RUN_AS_LOGIN_USER} "pip install --user \
  dsub \
  nbdime \
  nbstripout \
  pandas_gbq \
  plotnine \
  pre-commit \
  pylint \
  pytest"

# Install nbstripout for the login user in all git repositories.
${RUN_AS_LOGIN_USER} "nbstripout --install --global"

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
  curl -Os https://download.oracle.com/java/17/archive/jdk-17_linux-x64_bin.tar.gz && \
  tar xfz jdk-17_linux-x64_bin.tar.gz && \
  rm jdk-17_linux-x64_bin.tar.gz"

# Get the name local directory that was untarred (something like "jdk-17.0.7")
JAVA_DIRNAME="$(ls)"

# Move it to ~/.local
${RUN_AS_LOGIN_USER} "mv '${JAVA_DIRNAME}' '${USER_HOME_LOCAL_SHARE}'"

# Create a soft link in ~/.local/bin to the java runtime
ln -s "${USER_HOME_LOCAL_SHARE}/${JAVA_DIRNAME}/bin/java" "${USER_HOME_LOCAL_BIN}"
chown --no-dereference ${LOGIN_USER}:${LOGIN_USER} "${USER_HOME_LOCAL_BIN}/java"

# Clean up
popd
rmdir ${JAVA_INSTALL_TMP}

if [[ -n "${INSTANCE_CONTAINER}" ]]; then
  # The DeepLearning Docker images don't have SSH client software installed by default
  emit "Copying SSH client tools to ${USER_HOME_LOCAL_BIN}"
  cp "$(which ssh)" "${USER_HOME_LOCAL_BIN}"
  cp "$(which ssh-add)" "${USER_HOME_LOCAL_BIN}"
  chown ${LOGIN_USER}:${LOGIN_USER} "${USER_HOME_LOCAL_BIN}/ssh"
  chown ${LOGIN_USER}:${LOGIN_USER} "${USER_HOME_LOCAL_BIN}/ssh-add"

  # The DeepLearning Docker images don't have less installed by default
  emit "Copying 'less' to ${USER_HOME_LOCAL_BIN}"
  cp "$(which less)" "${USER_HOME_LOCAL_BIN}"
  chown ${LOGIN_USER}:${LOGIN_USER} "${USER_HOME_LOCAL_BIN}/less"
fi

emit "Installing Nextflow ..."

retry 5 install_nextflow
${RUN_AS_LOGIN_USER} "\
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

if ! AXON_SERVICE_URL="$(get_service_url "${TERRA_SERVER}" "axon")"; then
  >&2 echo "ERROR: ${TERRA_SERVER} is not a known Workbench server"
  exit 1
fi
readonly AXON_SERVICE_URL
USER_SERVICE_URL="$(get_service_url "${TERRA_SERVER}" "user")"
readonly USER_SERVICE_URL

if ! VERSION_JSON="$(curl -s "${AXON_SERVICE_URL}/version")"; then
  >&2 echo "ERROR: Failed to get version file from ${AXON_SERVICE_URL}"
  exit 1
fi
readonly VERSION_JSON

CLI_DISTRIBUTION_PATH="$(echo "${VERSION_JSON}" | jq -r '.cliDistributionPath')"
readonly CLI_DISTRIBUTION_PATH

CLI_VERSION="$(echo "${VERSION_JSON}" | jq -r '.latestSupportedCli')"
readonly CLI_VERSION

${RUN_AS_LOGIN_USER} "curl -L https://storage.googleapis.com/${CLI_DISTRIBUTION_PATH#gs://}/download-install.sh | WORKBENCH_CLI_VERSION=${CLI_VERSION} bash"
cp wb "${WORKBENCH_INSTALL_PATH}"

# Copy 'wb' to its legacy 'terra' name.
cp "${WORKBENCH_INSTALL_PATH}" "${WORKBENCH_LEGACY_PATH}"

# Set browser manual login since that's the only login supported from a Vertex AI Notebook VM
${RUN_AS_LOGIN_USER} "wb config set browser MANUAL"

# Set the CLI server based on the server that created the VM.
if [[ -n "${TERRA_SERVER}" ]]; then
  ${RUN_AS_LOGIN_USER} "wb server set --name=${TERRA_SERVER}"
fi

# Log in with app-default-credentials
${RUN_AS_LOGIN_USER} "wb auth login --mode=APP_DEFAULT_CREDENTIALS"
# Generate the bash completion script
${RUN_AS_LOGIN_USER} "wb generate-completion > '${USER_BASH_COMPLETION_DIR}/workbench'"

####################################
# Shell and notebook environment
####################################

# Set the CLI workspace id using the VM metadata, if set.
TERRA_WORKSPACE="$(get_metadata_value "instance/attributes/terra-workspace-id")"
readonly TERRA_WORKSPACE
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

# Keep in sync with Workbench CLI environment variables:
# https://github.com/verily-src/terra-tool-cli/blob/6c3d1ee2dd54aa62785da4113b83f5eba57d3c7f/src/main/java/bio/terra/cli/app/CommandRunner.java#L89

# *** Variables that are set by Leonardo for Cloud Environments
# (https://github.com/DataBiosphere/leonardo)

# OWNER_EMAIL is really the Workbench user account email address
OWNER_EMAIL="$(
  ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
  jq --raw-output ".userEmail")"
readonly OWNER_EMAIL

# GOOGLE_PROJECT is the project id for the GCP project backing the workspace
GOOGLE_PROJECT="$(
  ${RUN_AS_LOGIN_USER} "wb workspace describe --format=json" | \
  jq --raw-output ".googleProjectId")"
readonly GOOGLE_PROJECT

# PET_SA_EMAIL is the pet service account for the Workbench user and
# is specific to the GCP project backing the workspace
PET_SA_EMAIL="$(
  ${RUN_AS_LOGIN_USER} "wb auth status --format=json" | \
  jq --raw-output ".serviceAccountEmail")"
readonly PET_SA_EMAIL

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
export TERRA_USER_EMAIL='${OWNER_EMAIL}'
export OWNER_EMAIL='${OWNER_EMAIL}'
export GOOGLE_PROJECT='${GOOGLE_PROJECT}'
export PET_SA_EMAIL='${PET_SA_EMAIL}'

# Set up a few Workbench-specific convenience variables
export WORKBENCH_USER_EMAIL='${OWNER_EMAIL}'
export GOOGLE_CLOUD_PROJECT='${GOOGLE_PROJECT}'
export GOOGLE_SERVICE_ACCOUNT_EMAIL='${PET_SA_EMAIL}'
EOF

# Make the environment variables available to notebooks in container JupyterLab
if [[ -n "${INSTANCE_CONTAINER}" ]]; then

emit "Adding Workbench environment variables to jupyter_notebook_config.py ..."

cat << EOF >> "${NOTEBOOK_CONFIG}"

import os

# Set up a few legacy Workbench-specific convenience variables
os.environ['TERRA_USER_EMAIL']='${OWNER_EMAIL}'
os.environ['OWNER_EMAIL']='${OWNER_EMAIL}'
os.environ['GOOGLE_PROJECT']='${GOOGLE_PROJECT}'
os.environ['PET_SA_EMAIL']='${PET_SA_EMAIL}'

# Set up a few Workbench-specific convenience variables
os.environ['WORKBENCH_USER_EMAIL']='${OWNER_EMAIL}'
os.environ['GOOGLE_CLOUD_PROJECT']='${GOOGLE_PROJECT}'
os.environ['GOOGLE_SERVICE_ACCOUNT_EMAIL']='${PET_SA_EMAIL}'
EOF

fi

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

# Create a script for starting the ssh-agent, which will be run as a daemon
# process on boot.
#
# The ssh-agent information is deposited into the login user's HOME directory
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
chown ${LOGIN_USER}:${LOGIN_USER} "${WORKBENCH_SSH_AGENT_SCRIPT}"

# Create a systemd service to run the boot script on system boot
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
chown ${LOGIN_USER}:${LOGIN_USER} "${WORKBENCH_BOOT_SCRIPT}"

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

# Enable and start the startup service
systemctl daemon-reload
systemctl enable "${WORKBENCH_BOOT_SERVICE_NAME}"
systemctl start "${WORKBENCH_BOOT_SERVICE_NAME}"

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

# Indicate the end of Workbench customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

### END: Workbench-specific customizations ###
EOF

# Make sure the ~/.bashrc and ~/.bash_profile are owned by the login user
chown ${LOGIN_USER}:${LOGIN_USER} "${USER_BASHRC}"
chown ${LOGIN_USER}:${LOGIN_USER} "${USER_BASH_PROFILE}"

####################################
# Run a user provided startup script
####################################

# If the user has provided a startup script, run it after workbench setup but
# before restarting Jupyter and running tests.

USER_STARTUP_SCRIPT="$(get_metadata_value "instance/attributes/terra-user-startup-script")"
readonly USER_STARTUP_SCRIPT
if [[ -n "${USER_STARTUP_SCRIPT}" ]]; then
  readonly USER_STARTUP_SCRIPT_FILE="${USER_WORKBENCH_CONFIG_DIR}/user-startup-script.sh"

  # Copy the user's startup script to the user's .workbench directory
  emit "Downloading user startup script to ${USER_STARTUP_SCRIPT_FILE}..."
  if [[ "${USER_STARTUP_SCRIPT}" == gs://* ]]; then
      # If the URL starts with "gs://", use gsutil to download the file
      gsutil cp "${USER_STARTUP_SCRIPT}" "${USER_STARTUP_SCRIPT_FILE}"
  else
      # Otherwise, use curl to download the file
      curl -o "${USER_STARTUP_SCRIPT_FILE}" -L "${USER_STARTUP_SCRIPT}"
  fi
  chmod +x "${USER_STARTUP_SCRIPT_FILE}"

  # Run the user's startup script as the root user so that they may install packages
  emit "Running user startup script, output to ${USER_STARTUP_OUTPUT_FILE}..."
  "${USER_STARTUP_SCRIPT_FILE}" > ${USER_STARTUP_OUTPUT_FILE} 2>&1
fi

# TODO(BENCH-2612): use workbench CLI instead to get user profile.
IS_NON_GOOGLE_ACCOUNT="$(curl "${USER_SERVICE_URL}/api/profile?path=non_google_account" \
                    -H "accept: application/json" -H "Authorization: Bearer $(gcloud auth print-access-token)" \
                  | jq '.value')"
readonly IS_NON_GOOGLE_ACCOUNT

if [[ "${IS_NON_GOOGLE_ACCOUNT}" == "true" ]]; then

###########################################################
# Start a Proxy Agent to talk to workbench proxy service
###########################################################

  APP_PROXY="$(get_metadata_value "instance/attributes/terra-app-proxy")"
  readonly APP_PROXY
  TERRA_GCP_NOTEBOOK_RESOURCE_NAME="$(get_metadata_value "instance/attributes/terra-gcp-notebook-resource-name")"
  readonly TERRA_GCP_NOTEBOOK_RESOURCE_NAME
  if [[ -n "${APP_PROXY}" ]]; then
    emit "Using custom Proxy Agent"
    RESOURCE_ID="$(get_metadata_value "instance/attributes/terra-resource-id")"
    NEW_PROXY="https://${APP_PROXY}"
    NEW_PROXY_URL="${RESOURCE_ID}.${APP_PROXY}"
    readonly RESOURCE_ID
    readonly NEW_PROXY
    readonly NEW_PROXY_URL

    # Create a systemd service to start the workbench app proxy.
    cat << EOF > "${WORKBENCH_PROXY_AGENT_SERVICE}"
[Unit]
Description=Workbench App Proxy Agent Service
StartLimitIntervalSec=600

[Service]
StartLimitBurst=0
ExecStart=/opt/bin/proxy-forwarding-agent --proxy=${NEW_PROXY}/ --host=localhost:8080 --backend="${RESOURCE_ID}" --shim-path="websocket-shim" --health-check-path=/api/kernelspecs --health-check-interval-seconds=30
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start the startup service
    systemctl daemon-reload
    systemctl enable "${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"
    systemctl start "${WORKBENCH_PROXY_AGENT_SERVICE_NAME}"
    emit "Workbench Proxy Agent service started"
  
    # Set vertex AI metadata 'app-proxy-url' which UI exposes to users to access the VM.
    ${RUN_AS_LOGIN_USER} "wb resource update gcp-notebook --name=${TERRA_GCP_NOTEBOOK_RESOURCE_NAME} --new-metadata=app-proxy-url=${NEW_PROXY_URL}"
    emit "Updating app-proxy-url metadata"

    cat << EOF >> "${NOTEBOOK_CONFIG}"

c.ServerApp.allow_origin_pat += "|(^https://${NEW_PROXY_URL}$)"

EOF
  fi
fi

# Indicate the end of Workbench customizations of the jupyter_notebook_config.py
cat << EOF >> "${NOTEBOOK_CONFIG}"

### END: Workbench-specific customizations ###
EOF

####################################
# Restart JupyterLab or Docker so environment variables are picked up in Jupyter environment. See PF-2178.
####################################
if [[ -n "${INSTANCE_CONTAINER}" ]]; then
  emit "Restarting Docker service..."
  systemctl restart docker.service
else
  emit "Restarting Jupyter service..."
  systemctl restart jupyter.service
fi
####################################################################################
# Run a set of tests that should be invariant to the workspace or user configuration
####################################################################################

# Test java (existence and version)

emit "--  Checking if installed Java version is ${REQ_JAVA_VERSION} or higher"

# Get the current major version of Java: "11.0.12" => "11"
INSTALLED_JAVA_VERSION="$(${RUN_AS_LOGIN_USER} "${JAVA_INSTALL_PATH} -version" 2>&1 | awk -F\" '{ split($2,a,"."); print a[1]}')"
readonly INSTALLED_JAVA_VERSION
if [[ "${INSTALLED_JAVA_VERSION}" -lt ${REQ_JAVA_VERSION} ]]; then
  >&2 emit "ERROR: Java version detected (${INSTALLED_JAVA_VERSION}) is less than required (${REQ_JAVA_VERSION})"
  exit 1
fi

emit "SUCCESS: Java installed and version detected as ${INSTALLED_JAVA_VERSION}"

# Test nextflow
emit "--  Checking if Nextflow is properly installed"

INSTALLED_NEXTFLOW_VERSION="$(${RUN_AS_LOGIN_USER} "${NEXTFLOW_INSTALL_PATH} -v" | sed -e 's#nextflow version \(.*\)#\1#')"
readonly INSTALLED_NEXTFLOW_VERSION

emit "SUCCESS: Nextflow installed and version detected as ${INSTALLED_NEXTFLOW_VERSION}"

# Test Cromwell
emit "--  Checking if installed Cromwell version is ${CROMWELL_LATEST_VERSION}"

INSTALLED_CROMWELL_VERSION="$(${RUN_AS_LOGIN_USER} "java -jar ${CROMWELL_INSTALL_JAR} --version" | sed -e 's#cromwell \(.*\)#\1#')"
readonly INSTALLED_CROMWELL_VERSION
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

# Test Workbench CLI
emit "--  Checking if Workbench CLI is properly installed"

if [[ ! -e "${WORKBENCH_INSTALL_PATH}" ]]; then
  >&2 emit "ERROR: Workbench CLI not found at ${WORKBENCH_INSTALL_PATH}"
  exit 1
fi

INSTALLED_WORKBENCH_VERSION="$(${RUN_AS_LOGIN_USER} "${WORKBENCH_INSTALL_PATH} version")"
readonly INSTALLED_WORKBENCH_VERSION

if [[ -z "${INSTALLED_WORKBENCH_VERSION}" ]]; then
  >&2 emit "ERROR: Workbench CLI did not execute or did not return a version number"
  exit 1
fi

emit "SUCCESS: Workbench CLI installed and version detected as ${INSTALLED_WORKBENCH_VERSION}"

# SSH
emit "--  Checking if .ssh directory is properly set up"

if [[ ! -e "${USER_SSH_DIR}" ]]; then
  >&2 emit "ERROR: user SSH directory does not exist"
  exit 1
fi
SSH_DIR_MODE="$(stat -c "%a %G %U" "${USER_SSH_DIR}")"
readonly SSH_DIR_MODE
if [[ "${SSH_DIR_MODE}" != "700 jupyter jupyter" ]]; then
  >&2 emit "ERROR: user SSH directory permissions are incorrect: ${SSH_DIR_MODE}"
  exit 1
fi

# If the user didn't have an SSH key configured, then the id_rsa file won't exist.
# If they do have the file, check the permissions
if [[ -e "${USER_SSH_DIR}/id_rsa" ]]; then
  SSH_KEY_FILE_MODE="$(stat -c "%a %G %U" "${USER_SSH_DIR}/id_rsa")"
  readonly SSH_KEY_FILE_MODE
  if [[ "${SSH_KEY_FILE_MODE}" != "600 jupyter jupyter" ]]; then
    >&2 emit "ERROR: user SSH key file permissions are incorrect: ${SSH_DIR_MODE}/id_rsa"
    exit 1
  fi
fi


# GIT_IGNORE
emit "--  Checking if gitignore is properly installed"

INSTALLED_GITIGNORE="$(${RUN_AS_LOGIN_USER} "git config --global core.excludesfile")"
readonly INSTALLED_GITIGNORE

if [[ "${INSTALLED_GITIGNORE}" != "${GIT_IGNORE}" ]]; then
  >&2 emit "ERROR: gitignore not set up at ${GIT_IGNORE}"
  exit 1
fi

emit "SUCCESS: Gitignore installed at ${INSTALLED_GITIGNORE}"

# This block is for test only. If the notebook execute successfully down to
# here, we knows that the script executed successfully.
WORKBENCH_TEST_VALUE="$(get_metadata_value "instance/attributes/terra-test-value")"
readonly WORKBENCH_TEST_VALUE
if [[ -n "${WORKBENCH_TEST_VALUE}" ]]; then
  ${RUN_AS_LOGIN_USER} "wb resource update gcp-notebook --name=${TERRA_GCP_NOTEBOOK_RESOURCE_NAME} --new-metadata=terra-test-result=${WORKBENCH_TEST_VALUE}"
fi

# Let the UI know the script completed
set_guest_attributes "${STATUS_ATTRIBUTE}" "COMPLETE"
