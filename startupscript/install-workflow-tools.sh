#!/bin/bash

# install-workflow-tools.sh
#
# Install Cromwell, Nextflow, and dsub
#
# Note that this script is dependent on some functions and variables already being set up in "post-startup.sh":
#
# - LOGIN_USER
# - RUN_AS_LOGIN_USER: run command as app user
# - USER_BASHENV: path to user's ~/.bash_env file
# - USER_HOME_LOCAL_SHARE: path to user's .local/share dir
# - CLOUD: cloud environment, aws or gcp
# - retry: Retry a command multiple times

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CROMWELL_VERSION=90
readonly CROMWELL_INSTALL_PATH="${USER_HOME_LOCAL_SHARE}/cromwell"

#######################################
# Install Cromwell
#######################################
function install_cromwell() {
  ${RUN_AS_LOGIN_USER} "curl -L 'https://github.com/broadinstitute/cromwell/releases/download/${CROMWELL_VERSION}/cromwell-${CROMWELL_VERSION}.jar' -o cromwell.jar"
}

emit "Installing Cromwell ..."
retry 5 install_cromwell
${RUN_AS_LOGIN_USER} "mkdir -p '${CROMWELL_INSTALL_PATH}'"
mv cromwell.jar "${CROMWELL_INSTALL_PATH}"
# Add convenience variable
cat << EOF >> "${USER_BASHENV}"
export CROMWELL_JAR='${CROMWELL_INSTALL_PATH}/cromwell.jar'
EOF

#######################################
# Install Nextflow
#######################################
function install_nextflow() {
  ${RUN_AS_LOGIN_USER} "curl -s https://get.nextflow.io | bash"
}

emit "Installing Nextflow ..."
retry 5 install_nextflow
mv nextflow "/usr/local/bin"

#######################################
# Install dsub
#######################################
readonly VENV_PATH="${WORK_DIRECTORY}/.venv"
readonly DSUB_VENV_PATH="${VENV_PATH}/dsub_libs"
${RUN_AS_LOGIN_USER} "mkdir -p ${VENV_PATH}"

function install_dsub() {
  ${RUN_AS_LOGIN_USER} "${DSUB_VENV_PATH}/bin/pip install dsub"
}

# dsub only supported with GCP
if [[ "${CLOUD}" == "gcp" ]]; then
  emit "Installing dsub ..."

  apt install -y python3-venv
  PYTHON_COMMAND=$(command -v python3)
  ${RUN_AS_LOGIN_USER} "${PYTHON_COMMAND} -m venv ${DSUB_VENV_PATH}"
  retry 5 install_dsub

  # Add convenience variable & alias
  cat << EOF >> "${USER_BASHENV}"
  export DSUB_VENV_PATH='${DSUB_VENV_PATH}'
  alias dsub_activate='source ${DSUB_VENV_PATH}/bin/activate'
EOF

  # Add dsub to PATH
  ln -s "${DSUB_VENV_PATH}/bin/dsub" /usr/local/bin/dsub
fi