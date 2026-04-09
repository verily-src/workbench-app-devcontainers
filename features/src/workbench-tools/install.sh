#!/usr/bin/env bash

# install.sh installs common workbench tools in the devcontainer. Currently it
# only supports Debian-based systems (e.g. Ubuntu) on x86_64.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CLOUD="${CLOUD:-""}"
readonly USERNAME="${USERNAME:-"root"}"
readonly LIBRARIES_ENV_DIR="${LIBENV:-"/opt/conda/envs/workbench-ds"}"
readonly LIB_PYTHON_VERSION="${LIBPYTHONVERSION:-"3.14"}"
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
readonly CONDA_PACKAGES_SAMTOOLS=(
    "bioconda::bcftools>=1.23"
    "bioconda::htslib>=1.23" # includes bgzip and tabix
    "bioconda::samtools>=1.23"
)
readonly SAMTOOLS_ENV_DIR="${WORKBENCH_TOOLS_DIR}/samtools"

# Environment 2 contains the genomics CLI tools. They will be added to the
# PATH but will not be usable as Python libraries.
readonly CONDA_PACKAGES_BINARIES=(
    "conda-forge::python"
    "conda-forge::pip"
    "conda-forge::perl>=5.32"
    "bioconda::bedtools"
    "conda-forge::bgenix"
    "conda-forge::cromwell"
    "bioconda::ensembl-vep>=115"
    "bioconda::nextflow"
    "bioconda::plink"
    "bioconda::plink2"
    "bioconda::regenie"
    "bioconda::vcftools"
)
readonly BINARIES_ENV_DIR="${WORKBENCH_TOOLS_DIR}/binaries"

# Environment 3 contains data science Python libraries. These should be
# accessible from the user's default Python environment, which is why we install
# them separately and give the user control over whether to inject them into an
# existing environment or create a new one.
CONDA_PACKAGES_LIBRARIES=(
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
mamba create --prefix "${SAMTOOLS_ENV_DIR}" -y "${CONDA_PACKAGES_SAMTOOLS[@]}"

echo "Building Environment 2 (Genomics CLI Tools)..."
mamba create --prefix "${BINARIES_ENV_DIR}" -y "${CONDA_PACKAGES_BINARIES[@]}"

echo "Building Environment 3 (Python Libraries)..."
LIB_ENV_EXISTS=0

if [ -d "${LIBRARIES_ENV_DIR}" ]; then
    # SCENARIO A: Target environment already exists on host. Inject packages into it.
    LIB_ENV_EXISTS=1
    echo "Host environment detected at ${LIBRARIES_ENV_DIR}. Injecting data science packages..."

    if mamba list -p "${LIBRARIES_ENV_DIR}" --full-name python --json | jq -e 'length == 0' >/dev/null; then
        echo "No Python installation found in host environment. Adding python=${LIB_PYTHON_VERSION} to package list."
        CONDA_PACKAGES_LIBRARIES+=("conda-forge::python=${LIB_PYTHON_VERSION}")
    fi
    mamba install --prefix "${LIBRARIES_ENV_DIR}" -y "${CONDA_PACKAGES_LIBRARIES[@]}"
else
    # SCENARIO B: Target environment does not exist. Create it from scratch.
    echo "No host environment found. Creating standalone environment at ${LIBRARIES_ENV_DIR}..."
    mkdir -p "$(dirname "${LIBRARIES_ENV_DIR}")"

    CONDA_PACKAGES_LIBRARIES+=("conda-forge::python=${LIB_PYTHON_VERSION}")
    mamba create --prefix "${LIBRARIES_ENV_DIR}" -y "${CONDA_PACKAGES_LIBRARIES[@]}"
fi

# Install dsub via pip if on GCP. The conda version is outdated.
# dsub is installed in LIBRARIES_ENV_DIR because it can be used as a Python
# library, and users may want to install additional packages alongside it.
# PYTHONNOUSERSITE=1 prevents pip from seeing/modifying packages in user site-packages.
if [[ "${CLOUD}" == "gcp" ]]; then
    PYTHONNOUSERSITE=1 "${LIBRARIES_ENV_DIR}/bin/pip" install dsub
fi

# Force the perl and python scripts to use the correct perl/python
find -L "${BINARIES_ENV_DIR}/bin" -type f -executable -exec \
    sed -i --follow-symlinks \
        -e "1s|^#\!/usr/bin/env perl\\r\?$|#\!${BINARIES_ENV_DIR}/bin/perl|" \
        -e "1s|^#\!/usr/bin/env python\\r\?$|#\!${BINARIES_ENV_DIR}/bin/python|" {} \;

# Make the login user the owner of the conda environments
chown -R "${USERNAME}:" "${WORKBENCH_TOOLS_DIR}"
chown -R "${USERNAME}:" "${LIBRARIES_ENV_DIR}"

{
    echo "# Workbench Tools Configuration"
    
    # If we created a standalone Python libraries environment from scratch, make it the default terminal Python.
    # If it already existed (LIB_ENV_EXISTS=1), we leave the host image's PATH untouched to prevent shadowing.
    if [[ "${LIB_ENV_EXISTS}" == "0" ]]; then
        # shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
        printf 'export PATH="%s:$PATH"\n' "${LIBRARIES_ENV_DIR}/bin"
    fi
    
    # Set PATH to include workbench-tools binaries
    # shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
    printf 'export PATH="$PATH:%s"\n' "${SAMTOOLS_ENV_DIR}/bin:${BINARIES_ENV_DIR}/bin"

    # Set CROMWELL_JAR environment variable
    printf 'export CROMWELL_JAR="%s"\n' "${BINARIES_ENV_DIR}/share/cromwell/cromwell.jar"
} >> "${USER_HOME_DIR}/.bashrc"

# Allow .bashrc to be sourced in non-interactive shells
sed -i '/^# If not running interactively/,/esac/d' "${USER_HOME_DIR}/.bashrc" || true

# Make sure the login user is the owner of their .bashrc
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo "Workbench tools installation complete!"
