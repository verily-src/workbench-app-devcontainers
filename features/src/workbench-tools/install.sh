#!/usr/bin/env bash

# install.sh installs common workbench tools in the devcontainer. Currently it
# only supports Debian-based systems (e.g. Ubuntu) on x86_64.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CLOUD="${CLOUD:-""}"
readonly USERNAME="${USERNAME:-"root"}"
readonly LIB_ENV="${LIBENV:-"/opt/conda/envs/workbench-ds"}"
readonly LIB_PYTHON_VERSION="${LIBPYTHONVERSION:-"3.10"}"
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
# the other tools depend on old versions of these.
CONDA_PACKAGES_1=(
    "bioconda::bcftools"
    "bioconda::htslib" # includes bgzip and tabix
    "bioconda::samtools"
)

# Environment 2 contains the genomics CLI tools. They will be added to the
# PATH but will not be usable as Python libraries.
CONDA_PACKAGES_2=(
    "conda-forge::python=3.10"
    "conda-forge::pip"
    "conda-forge::perl==5.32.1"
    "bioconda::bedtools"
    "conda-forge::bgenix"
    "conda-forge::cromwell"
    "bioconda::ensembl-vep>=115.1"
    "bioconda::nextflow"
    "bioconda::plink"
    "bioconda::plink2"
    "bioconda::regenie"
    "bioconda::vcftools"
)

# Environment 3 contains data science Python libraries. These should be
# accessible from the user's default Python environment, which is why we install
# them separately and give the user control over whether to inject them into an
# existing environment or create a new one.
CONDA_PACKAGES_3=(
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

# Build isolated environments
mkdir -p "${WORKBENCH_TOOLS_DIR}"
echo "Building Environment 1 (Samtools family)..."
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/1" -y "${CONDA_PACKAGES_1[@]}"

echo "Building Environment 2 (Genomics CLI Tools)..."
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/2" -y "${CONDA_PACKAGES_2[@]}"

echo "Building Environment 3 (Python Libraries)..."
LIB_ENV_EXISTS=0

if [ -d "${LIB_ENV}" ]; then
    # SCENARIO A: Target environment already exists on host. Inject packages into it.
    LIB_ENV_EXISTS=1
    echo "Host environment detected at ${LIB_ENV}. Injecting data science packages..."

    if mamba list -p /opt/conda/envs/jupyter --full-name python --json | jq -e 'length == 0' >/dev/null; then
        echo "No Python installation found in host environment. Adding python=${LIB_PYTHON_VERSION} to package list."
        CONDA_PACKAGES_3+=("conda-forge::python=${LIB_PYTHON_VERSION}")
    fi
    mamba install --prefix "${LIB_ENV}" -y "${CONDA_PACKAGES_3[@]}"
else
    # SCENARIO B: Target environment does not exist. Create it from scratch.
    echo "No host environment found. Creating standalone environment at ${LIB_ENV}..."
    mkdir -p "$(dirname "${LIB_ENV}")"

    CONDA_PACKAGES_3+=("conda-forge::python=${LIB_PYTHON_VERSION}")
    mamba create --prefix "${LIB_ENV}" -y "${CONDA_PACKAGES_3[@]}"
fi

# Install dsub via pip if on GCP. The conda version is outdated.
# dsub is installed in LIB_ENV because it can be used as a Python library, and
# users may want to install additional packages alongside it.
# PYTHONNOUSERSITE=1 prevents pip from seeing/modifying packages in user site-packages.
if [[ "${CLOUD}" == "gcp" ]]; then
    PYTHONNOUSERSITE=1 "${LIB_ENV}/bin/pip" install dsub
fi

# Force the perl and python scripts to use the correct perl/python
find -L "${WORKBENCH_TOOLS_DIR}/2/bin" -type f -executable -exec \
    sed -i --follow-symlinks \
        -e "1s|^#\!/usr/bin/env perl\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/perl|" \
        -e "1s|^#\!/usr/bin/env python\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/python|" {} \;

# Make the login user the owner of the conda environments
chown -R "${USERNAME}:" "${WORKBENCH_TOOLS_DIR}"
chown -R "${USERNAME}:" "${LIB_ENV}"

{
    echo "# Workbench Tools Configuration"
    
    # If we created a standalone Python libraries environment from scratch, make it the default terminal Python.
    # If it already existed (LIB_ENV_EXISTS=1), we leave the host image's PATH untouched to prevent shadowing.
    if [[ "${LIB_ENV_EXISTS}" == "0" ]]; then
        # shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
        printf 'export PATH="%s:$PATH"\n' "${LIB_ENV}/bin"
    fi
    
    # Set PATH to include workbench-tools binaries
    # shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
    printf 'export PATH="$PATH:%s"\n' "${WORKBENCH_TOOLS_DIR}/1/bin:${WORKBENCH_TOOLS_DIR}/2/bin"

    # Set CROMWELL_JAR environment variable
    printf 'export CROMWELL_JAR="%s"\n' "${WORKBENCH_TOOLS_DIR}/2/share/cromwell/cromwell.jar"
} >> "${USER_HOME_DIR}/.bashrc"

# Allow .bashrc to be sourced in non-interactive shells
sed -i '/^# If not running interactively/,/esac/d' "${USER_HOME_DIR}/.bashrc" || true

# Make sure the login user is the owner of their .bashrc
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo "Workbench tools installation complete!"
