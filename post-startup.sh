#!/bin/bash

set -e -x

if [ $# -ne 2 ]; then
  echo "Usage: $0 user workDirectory"
  exit 1
fi

user="$1"
workDirectory="$2"
#######################################
# Emit a message with a timestamp
#######################################
function emit() {
 echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit

function get_metadata_value() {
 local metadata_path="${1}"
 curl --retry 5 -s -f \
   -H "Metadata-Flavor: Google" \
   "http://metadata/computeMetadata/v1/${metadata_path}"
}

readonly RUN_AS_USER="sudo -u ${user} bash -l -c"

readonly USER_BASH_COMPLETION_DIR="${workDirectory}/.bash_completion.d"
readonly USER_HOME_LOCAL_SHARE="${workDirectory}/.local/share"
readonly USER_TERRA_CONFIG_DIR="${workDirectory}/.terra"
readonly USER_SSH_DIR="${workDirectory}/.ssh"
readonly USER_BASHRC="${workDirectory}/.bashrc"
readonly USER_BASH_PROFILE="${workDirectory}/.bash_profile"
readonly POST_STARTUP_OUTPUT_FILE="${USER_TERRA_CONFIG_DIR}/post-startup-output.txt"

readonly JAVA_INSTALL_PATH="usr/bin/java"
readonly JAVA_INSTALL_TMP="${USER_TERRA_CONFIG_DIR}/javatmp"

# Variables for Terra-specific code installed on the VM
readonly TERRA_INSTALL_PATH="/usr/bin/terra"

readonly TERRA_GIT_REPOS_DIR="${workDirectory}/repos"

# Move to the /tmp directory to let any artifacts left behind by this script can be removed.
cd /tmp || exit

# Send stdout and stderr from this script to a file for debugging.
# Make the .terra directory as the user so that they own it and have correct linux permissions.
${RUN_AS_USER} "mkdir -p '${USER_TERRA_CONFIG_DIR}'"
exec >> "${POST_STARTUP_OUTPUT_FILE}"
exec 2>&1

# The apt package index may not be clean when we run; resynchronize
apt-get update
apt install -y jq curl tar

# Create the target directories for installing into the HOME directory
${RUN_AS_USER} "mkdir -p '${USER_BASH_COMPLETION_DIR}'"
${RUN_AS_USER} "mkdir -p '${USER_HOME_LOCAL_SHARE}'"

# As described above, have the ~/.bash_profile source the ~/.bashrc
cat << EOF >> "${USER_BASH_PROFILE}"

if [[ -e ~/.bashrc ]]; then
 source ~/.bashrc
fi

EOF

# Indicate the start of Terra customizations of the ~/.bashrc
cat << EOF >> "${USER_BASHRC}"

# Prepend "/usr/bin" (if not already in the path)
if [[ "${PATH}:" != "/usr/bin:"* ]]; then
  export PATH=/usr/bin:${PATH}
fi
EOF

emit "Installing Java JDK ..."

# Set up a known clean directory for downloading the TAR and unzipping it.
${RUN_AS_USER} "mkdir -p '${JAVA_INSTALL_TMP}'"
pushd "${JAVA_INSTALL_TMP}"

# Download the latest Java 17, untar it, and remove the TAR file
${RUN_AS_USER} "\
 curl -Os https://download.oracle.com/java/17/latest/jdk-17_linux-x64_bin.tar.gz && \
 tar xfz jdk-17_linux-x64_bin.tar.gz && \
 rm jdk-17_linux-x64_bin.tar.gz"

# Get the name local directory that was untarred (something like "jdk-17.0.7")
JAVA_DIRNAME="$(ls)"

# Move it to ~/.local
${RUN_AS_USER} "mv '${JAVA_DIRNAME}' '${USER_HOME_LOCAL_SHARE}'"

# Create a soft link in /usr/bin to the java runtime
ln -sf "${USER_HOME_LOCAL_SHARE}/${JAVA_DIRNAME}/bin/java" "/usr/bin"
chown --no-dereference ${user}:${user} "/usr/bin/java"

# Clean up
popd
rmdir ${JAVA_INSTALL_TMP}

# Install & configure the Terra CLI
emit "Installing the Terra CLI ..."

${RUN_AS_USER} "\
 curl -L https://github.com/DataBiosphere/terra-cli/releases/latest/download/download-install.sh | bash"

cp terra ${TERRA_INSTALL_PATH}

# Set browser manual login since that's the only login supported from a Vertex AI Notebook VM
${RUN_AS_USER} "terra config set browser MANUAL"

# Set the CLI terra server based on the terra server that created the VM.
readonly TERRA_SERVER="$(get_metadata_value "instance/attributes/terra-cli-server")"
if [[ -n "${TERRA_SERVER}" ]]; then
 ${RUN_AS_USER} "terra server set --name=${TERRA_SERVER}"
fi

# Log in with app-default-credentials
${RUN_AS_USER} "terra auth login --mode=APP_DEFAULT_CREDENTIALS"
# Generate the bash completion script
${RUN_AS_USER} "terra generate-completion > '${USER_BASH_COMPLETION_DIR}/terra'"

####################################
# Shell and notebook environment
####################################

# Set the CLI terra workspace id using the VM metadata, if set.
readonly TERRA_WORKSPACE="$(get_metadata_value "instance/attributes/terra-workspace-id")"
if [[ -n "${TERRA_WORKSPACE}" ]]; then
 ${RUN_AS_USER} "terra workspace set --id='${TERRA_WORKSPACE}'"
fi

#################
# bash completion
#################
#
# bash_completion is installed on Vertex AI notebooks, but the installed
# completion scripts are *not* sourced from /etc/profile.
# If we need it system-wide, we can install it there, but otherwise, let's
# keep changes localized to the user.
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
${RUN_AS_USER} "mkdir -p ${USER_SSH_DIR} --mode 0700"

# Get the user's SSH key from Terra, and if set, write it to the user's .ssh directory
${RUN_AS_USER} "\
 install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa.tmp' && \
 terra user ssh-key get --include-private-key --format=JSON >> '${USER_SSH_DIR}/id_rsa.tmp' || true"
if [[ -s "${USER_SSH_DIR}/id_rsa.tmp" ]]; then
 ${RUN_AS_USER} "\
   install --mode 0600 /dev/null '${USER_SSH_DIR}/id_rsa' && \
   jq -r '.privateSshKey' '${USER_SSH_DIR}/id_rsa.tmp' > '${USER_SSH_DIR}/id_rsa'"
fi
rm -f "${USER_SSH_DIR}/id_rsa.tmp"

# Set the github known_hosts
apt-get update
apt-get install -y openssh-client
${RUN_AS_USER} "ssh-keyscan -H github.com >> '${USER_SSH_DIR}/known_hosts'"

# Create git repos directory
${RUN_AS_USER} "mkdir -p '${TERRA_GIT_REPOS_DIR}'"

# Attempt to clone all the git repo references in the workspace. If the user's ssh key does not exist or doesn't have access
# to the git references, the corresponding git repo cloning will be skipped.
# Keep this as last thing in script. There will be integration test for git cloning (PF-1660). If this is last thing, then
# integration test will ensure that everything in script worked.
${RUN_AS_USER} "cd '${TERRA_GIT_REPOS_DIR}' && terra git clone --all"


#############################
# Mount buckets
#############################
emit "Installing GCS fuse..."

apt-get install -y fuse lsb-core

export GCSFUSE_REPO=gcsfuse-\lsb_release -c -s\
echo "deb https://packages.cloud.google.com/apt $GCSFUSE_REPO main" | tee /etc/apt/sources.list.d/gcsfuse.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add -

apt-get update
apt-get install -y gcsfuse

${RUN_AS_USER} "terra resource mount"

