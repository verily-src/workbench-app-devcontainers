#!/usr/bin/env bash

# install.sh installs common workbench tools in the devcontainer. Currently it
# only supports Debian-based systems (e.g. Ubuntu) on x86_64.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CLOUD="${CLOUD:-""}"
INSTALL_FROM_SOURCE="${INSTALLFROMSOURCE:-"false"}"
if [[ "$CLOUD" = "gcp" ]]; then
    INSTALL_FROM_SOURCE="true"
fi
readonly INSTALL_FROM_SOURCE

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

WORKDIR="$(mktemp -d)"
readonly WORKDIR

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

function build_samtool() {
    local -r NAME="$1"
    local -r VERSION="$2"
    local -r SHA256="$3"
    local -r URL="https://github.com/samtools/$1/releases/download/$VERSION/$1-$VERSION.tar.bz2"

    check_packages \
        zlib1g-dev \
        libbz2-dev \
        liblzma-dev \
        libcurl4-openssl-dev

    rm -rf "${WORKDIR:?}/$1"
    mkdir -p "$WORKDIR/$1"
    pushd "$WORKDIR/$1"

    curl -sSL "$URL" -o "$1-$VERSION.tar.bz2"
    if [ "$SHA256" != "$(sha256sum "$1-$VERSION.tar.bz2" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for $1."
        exit 1
    fi

    tar -xjf "$1-$VERSION.tar.bz2"
    pushd "$1-$VERSION"
    ./configure --prefix=/usr/local
    make
    make install
    popd

    popd
}

function build_regenie() {
    local -r NAME="$1"
    local -r VARIANT="$2"
    local -r VERSION="$3"
    local -r SHA256="$4"
    local -r URL="https://github.com/rgcgithub/regenie/releases/download/v$VERSION/regenie_v$VERSION.gz_$VARIANT.zip"

    rm -rf "${WORKDIR:?}/$NAME"
    mkdir -p "$WORKDIR/$NAME"
    pushd "$WORKDIR/$NAME"

    curl -sSL "$URL" -o "regenie_v$VERSION.gz_$VARIANT.zip"
    if [ "$SHA256" != "$(sha256sum "regenie_v$VERSION.gz_$VARIANT.zip" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for $NAME."
        exit 1
    fi

    unzip "regenie_v$VERSION.gz_$VARIANT.zip"
    mv "regenie_v$VERSION.gz_$VARIANT" "/usr/local/bin/$NAME"

    popd
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

function install_python() {
    # Only install python3 with the package manager if it is not already
    # installed. python may have been installed with other methods (e.g. conda).
    if ! type python3 > /dev/null 2>&1; then
        check_packages python3 python3-pip python3-venv
    fi
}

function install_bcftools() {
    local -r SHA256="f2ab9e2f605b1203a7e9cbfb0a3eb7689322297f8c34b45dc5237fe57d98489f"
    build_samtool "bcftools" "1.22" "$SHA256"
}

function install_samtools() {
    check_packages libncurses5-dev

    local -r SHA256="02aa5cd0ba52e06c2080054e059d7d77a885dfe9717c31cd89dfe7a4047eda0e"
    build_samtool "samtools" "1.22.1" "$SHA256"
}

function install_htslib() {
    local -r SHA256="3dfa6eeb71db719907fe3ef7c72cb2ec9965b20b58036547c858c89b58c342f7"
    build_samtool "htslib" "1.22.1" "$SHA256"
}

function install_bgen() {
    local -r VERSION="v1.1.7"
    local -r SHA256="f6c50a321ece9b92a7b8054bbbdbcfa4ddc159a98c3f4e81ec9f2852695d880b"
    local -r URL="https://enkre.net/cgi-bin/code/bgen/tarball/$VERSION/bgen.tar.gz"

    check_packages zlib1g-dev

    rm -rf "${WORKDIR:?}/bgen"
    mkdir -p "$WORKDIR/bgen"
    pushd "$WORKDIR/bgen"

    curl -sSL "$URL" -o "bgen.tar.gz"
    if [ "$SHA256" != "$(sha256sum "bgen.tar.gz" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for bgen."
        exit 1
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

function install_plink() {
    local -r VERSION="20250615"
    local -r SHA256="52571583a4b1a648ed598322e0df0e71ce5d817a23c3c37b2291bd21b408a955"
    local -r URL="https://s3.amazonaws.com/plink1-assets/plink_linux_x86_64_$VERSION.zip"

    rm -rf "${WORKDIR:?}/plink"
    mkdir -p "$WORKDIR/plink"
    pushd "$WORKDIR/plink"

    curl -sSL "$URL" -o "plink_linux_x86_64_$VERSION.zip"
    if [ "$SHA256" != "$(sha256sum "plink_linux_x86_64_$VERSION.zip" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for plink."
        exit 1
    fi

    unzip "plink_linux_x86_64_$VERSION.zip"
    mv "plink" "/usr/local/bin/plink"

    popd
}

function install_plink2() {
    local -r VERSION="20250707"
    local -r SHA256="330e15a1e9de9742811e5bb1eb098ed9eeb78d58d97533622798b2dbcc62fac2"
    local -r URL="https://s3.amazonaws.com/plink2-assets/alpha6/plink2_linux_x86_64_$VERSION.zip"

    rm -rf "${WORKDIR:?}/plink2"
    mkdir -p "$WORKDIR/plink2"
    pushd "$WORKDIR/plink2"

    curl -sSL "$URL" -o "plink2_linux_x86_64_$VERSION.zip"
    if [ "$SHA256" != "$(sha256sum "plink2_linux_x86_64_$VERSION.zip" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for plink2."
        exit 1
    fi

    unzip "plink2_linux_x86_64_$VERSION.zip"
    mv "plink2" "/usr/local/bin/plink2"

    popd
}

function install_vcftools() {
    local -r VERSION="0.1.17"
    local -r SHA256="b9e0e1c3e86533178edb35e02c6c4de9764324ea0973bebfbb747018c2d2a42c"
    local -r URL="https://github.com/vcftools/vcftools/releases/download/v$VERSION/vcftools-$VERSION.tar.gz"

    rm -rf "${WORKDIR:?}/vcftools"
    mkdir -p "$WORKDIR/vcftools"
    pushd "$WORKDIR/vcftools"

    curl -sSL "$URL" -o "vcftools-$VERSION.tar.gz"
    if [ "$SHA256" != "$(sha256sum "vcftools-$VERSION.tar.gz" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for vcftools."
        exit 1
    fi

    tar -xf "vcftools-$VERSION.tar.gz"
    pushd "vcftools-$VERSION"
    ./configure --prefix=/usr/local
    make
    make install

    rm -rf /usr/local/bin/vcftools_perl5
    mv src/perl /usr/local/lib/vcftools_perl5
    export PERL5LIB="${PERL5LIB:-}:/usr/local/lib/vcftools_perl5"
    # We want this to output $PERL5LIB without expansion
    # shellcheck disable=SC2016
    echo 'export PERL5LIB=${PERL5LIB:-}:/usr/local/lib/vcftools_perl5' > /etc/profile.d/vcftools_perl.sh

    popd

    popd
}

function install_regenie() {
    local -r SHA256="8d5b64cebd7e33933c9b92dd97ccffedfcc727d7be68fe8a6bec1eb959d10963"
    build_regenie "regenie" "x86_64_Linux" "4.1" "$SHA256"
}

function install_regenie_mkl() {
    local -r SHA256="27ef359d3d37f204d6ed723c177f3928e2168914541a97708f81d21d853fc67c"
    build_regenie "regenie_mkl" "x86_64_Linux_mkl" "4.1" "$SHA256"
}

function install_vep() {
    local -r VERSION="114.2"
    local -r SHA256="59b3c8bf560b4f2febfb46e25d7312a0779ab6cffc25a254d4ff7ec02571e4f4"
    local -r URL="https://github.com/Ensembl/ensembl-vep/archive/refs/tags/release/$VERSION.tar.gz"
    local -r TARFILE="ensembl-vep-release-$VERSION.tar.gz"

    check_packages \
        libmysqlclient-dev \
        libcrypto++-dev

    rm -rf "${WORKDIR:?}/ensembl-vep"
    mkdir -p "$WORKDIR/ensembl-vep"
    pushd "$WORKDIR/ensembl-vep"

    PERL_MM_USE_DEFAULT=1 cpan App::cpanminus
    cpanm \
        Module::Build \
        List::MoreUtils \
        LWP::Simple \
        Archive::Zip \
        DBD::mysql \
        DBI \
        JSON \
        Set::IntervalTree

    curl -sSL "$URL" -o "$TARFILE"
    if [ "$SHA256" != "$(sha256sum "$TARFILE" | awk '{print $1}')" ]; then
        echo "Error: SHA256 checksum mismatch for vep."
        exit 1
    fi

    tar -xf "$TARFILE"
    pushd "ensembl-vep-release-$VERSION"

    perl INSTALL.pl --AUTO a --NO_TEST

    rm -rf /opt/ensembl-vep
    cp -r . /opt/ensembl-vep

    ln -s /opt/ensembl-vep/vep /usr/local/bin/vep
    ln -s /opt/ensembl-vep/filter_vep /usr/local/bin/filter_vep
    ln -s /opt/ensembl-vep/variant_recoder /usr/local/bin/variant_recoder
    ln -s /opt/ensembl-vep/haplo /usr/local/bin/haplo

    popd

    popd
}

echo "Starting workbench tools installation..."

if ! type apt-get > /dev/null 2>&1; then
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
    zip \
    unzip \
    tar \
    bzip2 \
    bedtools

install python
install plink
install plink2
install regenie
install regenie_mkl

if [[ "${INSTALL_FROM_SOURCE}" = "true" ]]; then
    install bcftools
    install samtools
    install htslib # includes bgzip and tabix
    install bgen # depends on python
    install vcftools
    install vep
fi

echo "Done!"
