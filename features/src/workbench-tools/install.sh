#!/usr/bin/env bash

# install.sh installs common workbench tools in the devcontainer. Currently it
# only supports Debian-based systems (e.g. Ubuntu) on x86_64.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CLOUD="${CLOUD:-""}"
readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-"/home/${USERNAME}"}"
if [[ "${USER_HOME_DIR}" == "/home/root" ]]; then
    USER_HOME_DIR="/root"
fi
readonly USER_HOME_DIR

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

WORKDIR="$(mktemp -d)"
readonly WORKDIR

readonly WORKBENCH_TOOLS_DIR="/opt/workbench-tools"

function cleanup() {
    rm -rf "${WORKDIR:?}"
    rm -rf /var/lib/apt/lists/*
}

trap 'cleanup' EXIT

function apt_get_update() {
    if [ "$(find /var/lib/apt/lists/* | wc -l)" = "0" ]; then
        echo "Running apt-get update..."
        apt-get update -y
    fi
}

# Checks if packages are installed and installs them if not
function check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update
        apt-get -y install --no-install-recommends "$@"
    fi
}

echo "Starting workbench tools installation..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

check_packages \
    ca-certificates \
    build-essential \
    pkg-config \
    curl \
    git \
    sed \
    sudo \
    tar

if ! mamba --version &>/dev/null; then
    source ./install-conda.sh
fi

# Install the samtools family of tools in a separate environment since some of
# the other tools depend on old versions of these. This will take priority in
# the PATH.
CONDA_PACKAGES_1=(
    "bcftools"
    "htslib" # includes bgzip and tabix
    "samtools"
)

CONDA_PACKAGES_2=(
    "python=3.12"
    "pip"
    "perl==5.32.1"
    "bedtools"
    "conda-forge::bgenix"
    "conda-forge::cromwell"
    "ensembl-vep>=115.1"
    "nextflow"
    "plink"
    "plink2"
    "regenie"
    "vcftools"
    "conda-forge::google-cloud-storage"
    "conda-forge::ipykernel"
    "conda-forge::ipywidgets"
    "conda-forge::jupyter"
    "conda-forge::openai"
    "conda-forge::matplotlib"
    "conda-forge::numpy"
    "conda-forge::plotly"
    "conda-forge::pandas"
    "conda-forge::seaborn"
    "conda-forge::scikit-learn"
    "conda-forge::scipy"
    "conda-forge::tqdm"
)

mkdir -p "${WORKBENCH_TOOLS_DIR}"
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/1" -c bioconda -y "${CONDA_PACKAGES_1[@]}"
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/2" -c bioconda -y "${CONDA_PACKAGES_2[@]}"

# Install dsub via pip if on GCP. The conda version is outdated.
if [[ "${CLOUD}" == "gcp" ]]; then
    "${WORKBENCH_TOOLS_DIR}/2/bin/pip" install dsub
fi

# Force the perl and python scripts to use the correct perl/python
find -L "${WORKBENCH_TOOLS_DIR}/2/bin" -type f -executable -exec \
    sed -i --follow-symlinks \
        -e "1s|^#\!/usr/bin/env perl\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/perl|" \
        -e "1s|^#\!/usr/bin/env python\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/python|" {} \;

# Make the login user the owner of the conda environment
chown -R "${USERNAME}:" "${WORKBENCH_TOOLS_DIR}"

{
    # Set PATH to include workbench-tools binaries
    # shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
    printf 'export PATH="%s:$PATH"\n' "${WORKBENCH_TOOLS_DIR}/1/bin:${WORKBENCH_TOOLS_DIR}/2/bin"

    # Set CROMWELL_JAR environment variable
    printf 'export CROMWELL_JAR="%s"\n' "${WORKBENCH_TOOLS_DIR}/2/share/cromwell/cromwell.jar"

    # Make dsub a function that includes the correct PYTHONPATH. NeMo sets
    # PYTHONPATH so we need to override it here. We use a function instead of an
    # alias because aliases are not expanded in non-interactive shells.
    # shellcheck disable=SC2016 # we want $PYTHONPATH to be evaluated at runtime
    printf 'function dsub() (PYTHONPATH="%s/2/lib/python3.12/site-packages:${PYTHONPATH:-}" "%s/2/bin/dsub" "$@")\n' "${WORKBENCH_TOOLS_DIR}" "${WORKBENCH_TOOLS_DIR}" 
} >> "${USER_HOME_DIR}/.bashrc"

# Allow .bashrc to be sourced in non-interactive shells
sed -i '/^# If not running interactively/,/esac/d' "${USER_HOME_DIR}/.bashrc" || true

# Make sure the login user is the owner of their .bashrc
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo "Done!"
