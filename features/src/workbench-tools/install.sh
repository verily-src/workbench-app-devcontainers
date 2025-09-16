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
    rm -rf "/var/lib/apt/lists/*"
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

function retry() {
  local -r max_attempts="$1"
  shift
  local -r command=("$@")

  local attempt
  for ((attempt = 1; attempt < max_attempts; attempt++)); do
    # Run the command and return if success
    if "${command[@]}"; then
      return
    fi

    # Sleep a bit in case the problem is a transient network/server issue
    if ((attempt < max_attempts)); then
      echo "Retrying ${command[*]} in 5 seconds" # send to get_message
      sleep 5
    fi
  done

  # Execute without the if/then protection such that the exit code propagates
  "${command[@]}"
}
readonly -f retry

function install() {
    local -r NAME="$1"
    local -r INSTALL_FUNC="install_$NAME"

    printf "\nStarting installation for %s\n\n" "$NAME"
    if retry 5 "$INSTALL_FUNC"; then
        printf "\nInstallation for %s completed successfully.\n\n" "$NAME"
    else
        retval=$?
        printf "\nInstallation for %s failed.\n\n" "$NAME"
        return $retval
    fi
}

function install_bgen() {
    local -r VERSION="v1.1.7"
    local -r SHA256="f6c50a321ece9b92a7b8054bbbdbcfa4ddc159a98c3f4e81ec9f2852695d880b"
    local -r URL="https://enkre.net/cgi-bin/code/bgen/tarball/$VERSION/bgen.tar.gz"

    check_packages zlib1g-dev

    rm -rf "${WORKDIR:?}/bgen"
    mkdir -p "$WORKDIR/bgen"
    pushd "$WORKDIR/bgen"

    if ! curl -sSLf "$URL" -o "bgen.tar.gz"; then
        echo "Error: failed to download bgen."
        return 1
    fi
    if [ "$SHA256" != "$(sha256sum "bgen.tar.gz" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for bgen."
        return 1
    fi

    tar -xf "bgen.tar.gz"
    pushd "bgen"

    # Use python3 since python may not exist
    sed -i 's|^#!/usr/bin/env python$|#!/usr/bin/env python3|' ./waf

    # Build with C++11 standard
    sed -i "/-std=c++11/! s/cfg.env.CXXFLAGS = \[ /\0'-std=c++11', /" ./wscript

    ./waf configure
    ./waf install
    popd

    popd
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
    "python"
    "pip"
    "bedtools"
    "conda-forge::cromwell"
    "ensembl-vep"
    "nextflow"
    "plink"
    "plink2"
    "regenie"
    "vcftools"
)

if [[ "${CLOUD}" == "gcp" ]]; then
    CONDA_PACKAGES_2+=("dsub")
fi

mkdir -p "${WORKBENCH_TOOLS_DIR}"
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/1" -c bioconda -y "${CONDA_PACKAGES_1[@]}"
mamba create --prefix "${WORKBENCH_TOOLS_DIR}/2" -c bioconda -y "${CONDA_PACKAGES_2[@]}"

# Vcf perl modules are not installed by default
cp -LR "${WORKBENCH_TOOLS_DIR}/2/anaconda/envs/_build/lib/perl5/site_perl/5.22.0/." "${WORKBENCH_TOOLS_DIR}/2/lib/perl5/site_perl/5.22.0/"

# Force the perl and python scripts to use the correct perl/python
find -L "${WORKBENCH_TOOLS_DIR}/2/bin" -type f -executable -exec \
    sed -i --follow-symlinks \
        -e "1s|^#\!/usr/bin/env perl\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/perl|" \
        -e "1s|^#\!/usr/bin/env python\\r\?$|#\!${WORKBENCH_TOOLS_DIR}/2/bin/python|" {} \;

# Make the login user the owner of the conda environment
chown -R "${USERNAME}:conda" "${WORKBENCH_TOOLS_DIR}"

# Set PATH to include workbench-tools binaries
# shellcheck disable=SC2016 # we want $PATH to be evaluated at runtime
printf 'export PATH="%s:$PATH"\n' "${WORKBENCH_TOOLS_DIR}/1/bin:${WORKBENCH_TOOLS_DIR}/2/bin" >> "${USER_HOME_DIR}/.bashrc"

# Set CROMWELL_JAR environment variable
printf 'export CROMWELL_JAR="%s"\n' "${WORKBENCH_TOOLS_DIR}/2/share/cromwell/cromwell.jar" >> "${USER_HOME_DIR}/.bashrc"

# Make sure the login user is the owner of their .bashrc
chown -R "${USERNAME}:${USERNAME}" "${USER_HOME_DIR}/.bashrc"

install bgen # depends on python

echo "Done!"

