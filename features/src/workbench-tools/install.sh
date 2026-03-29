#!/usr/bin/env bash

# install.sh installs common workbench tools in the devcontainer.
set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CLOUD="${CLOUD:-""}"
readonly USERNAME="${USERNAME:-"root"}"
readonly LIBRARIES_ENV_DIR="${LIBENV:-"/opt/conda/envs/workbench-ds"}"
# Downgraded to 3.10 for better compatibility with scvi-tools/spatialdata
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
        apt-get update -y
    fi
}

function check_packages() {
    if ! dpkg -s "$@" > /dev/null 2>&1; then
        apt_get_update
        apt-get -y install --no-install-recommends "$@"
    fi
}

check_packages ca-certificates build-essential pkg-config curl git sed sudo tar

if ! mamba --version &>/dev/null; then
    source ./install-conda.sh
fi

# Environment 1: Samtools
readonly CONDA_PACKAGES_SAMTOOLS=(
    "bioconda::bcftools>=1.23"
    "bioconda::htslib>=1.23"
    "bioconda::samtools>=1.23"
)
readonly SAMTOOLS_ENV_DIR="${WORKBENCH_TOOLS_DIR}/samtools"

# Environment 2: Genomics CLI
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

# Environment 3: RefinedScience Single Cell (Python + R)
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
    "conda-forge::snakemake"
    "bioconda::bioconductor-deseq2"
    "conda-forge::r-seurat"
    "conda-forge::scanpy"
    "conda-forge::muon"
    "conda-forge::squidpy"
)

# Packages to install via PIP to avoid Mamba solver conflicts
readonly PIP_PACKAGES_OMICS=(
    "anndata"
    "mudata"
    "spatialdata"
    "scvi-tools"
    "pertpy"
    "decoupler"
)

mkdir -p "${WORKBENCH_TOOLS_DIR}"

echo "Building Env 1..."
mamba create --prefix "${SAMTOOLS_ENV_DIR}" -y "${CONDA_PACKAGES_SAMTOOLS[@]}"

echo "Building Env 2..."
mamba create --prefix "${BINARIES_ENV_DIR}" -y "${CONDA_PACKAGES_BINARIES[@]}"

echo "Building/Updating Env 3 (Libraries)..."
LIB_ENV_EXISTS=0
if [ -d "${LIBRARIES_ENV_DIR}" ]; then
    LIB_ENV_EXISTS=1
    mamba install --prefix "${LIBRARIES_ENV_DIR}" -y "${CONDA_PACKAGES_LIBRARIES[@]}"
else
    mkdir -p "$(dirname "${LIBRARIES_ENV_DIR}")"
    CONDA_PACKAGES_LIBRARIES+=("conda-forge::python=${LIB_PYTHON_VERSION}")
    mamba create --prefix "${LIBRARIES_ENV_DIR}" -y "${CONDA_PACKAGES_LIBRARIES[@]}"
fi

# Install PIP packages into Env 3
echo "Installing specialized omics packages via PIP..."
PYTHONNOUSERSITE=1 "${LIBRARIES_ENV_DIR}/bin/pip" install "${PIP_PACKAGES_OMICS[@]}"

if [[ "${CLOUD}" == "gcp" ]]; then
    PYTHONNOUSERSITE=1 "${LIBRARIES_ENV_DIR}/bin/pip" install dsub
fi

# Cleanup permissions and shebangs
find -L "${BINARIES_ENV_DIR}/bin" -type f -executable -exec \
    sed -i --follow-symlinks \
        -e "1s|^#\!/usr/bin/env perl\\r\?$|#\!${BINARIES_ENV_DIR}/bin/perl|" \
        -e "1s|^#\!/usr/bin/env python\\r\?$|#\!${BINARIES_ENV_DIR}/bin/python|" {} \;

chown -R "${USERNAME}:" "${WORKBENCH_TOOLS_DIR}"
chown -R "${USERNAME}:" "${LIBRARIES_ENV_DIR}"

{
    echo "# Workbench Tools Configuration"
    if [[ "${LIB_ENV_EXISTS}" == "0" ]]; then
        printf 'export PATH="%s:$PATH"\n' "${LIBRARIES_ENV_DIR}/bin"
    fi
    printf 'export PATH="$PATH:%s"\n' "${SAMTOOLS_ENV_DIR}/bin:${BINARIES_ENV_DIR}/bin"
    printf 'export CROMWELL_JAR="%s"\n' "${BINARIES_ENV_DIR}/share/cromwell/cromwell.jar"
} >> "${USER_HOME_DIR}/.bashrc"

sed -i '/^# If not running interactively/,/esac/d' "${USER_HOME_DIR}/.bashrc" || true
chown "${USERNAME}:" "${USER_HOME_DIR}/.bashrc"

echo "Workbench tools installation complete!"