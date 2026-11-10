#!/usr/bin/env bash

# install.sh installs the vllm-model feature: vLLM in its own virtual environment
# (/opt/vllm) and the model scripts in /opt/vllm-model. See README.md.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly USERNAME="${USERNAME:-"root"}"
USER_HOME_DIR="${USERHOMEDIR:-"/home/${USERNAME}"}"
if [[ "${USER_HOME_DIR}" == "/home/root" ]]; then
    USER_HOME_DIR="/root"
fi
readonly USER_HOME_DIR

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

readonly INSTALL_DIR="/opt/vllm-model"
readonly VENV="/opt/vllm"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

function cleanup() {
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

echo "Starting vllm-model installation..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# gcc and python3-dev: vLLM's torch.compile builds small C helpers at start-up
# and the Humming kernels JIT-compile with NVRTC; both need a C toolchain and
# the Python headers in the image. jq: the scripts read the catalog with it.
check_packages ca-certificates curl gcc jq python3 python3-dev python3-pip python3-venv

# vLLM in its own virtual environment, pinned by vllm-release.json. The wheel brings PyTorch
# and CUDA 13.0 from pip; the host needs only the NVIDIA driver. FlashInfer must not compile
# at start-up (the pip toolchain cannot), so its prebuilt kernels are installed: the
# flashinfer-jit-cache shim without its dependencies, which are the kernel sets for every
# architecture (2.4 GB), plus the A100 (sm80) and H100 (sm90a) sets. `pip check` would flag
# that, so it runs before the shim. The version check reads package metadata: `vllm --version`
# probes for a GPU, and the image is built without one.
release_version="$(jq -r .version "${FEATURE_DIR}/vllm-release.json")"
flashinfer_version="$(jq -r .flashinfer_version "${FEATURE_DIR}/vllm-release.json")"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --no-cache-dir --upgrade pip
"${VENV}/bin/pip" install --no-cache-dir "vllm==${release_version}"
"${VENV}/bin/pip" install --no-cache-dir --extra-index-url https://flashinfer.ai/whl/cu130/ \
    "flashinfer-cubin @ https://github.com/flashinfer-ai/flashinfer/releases/download/v${flashinfer_version}/flashinfer_cubin-${flashinfer_version}-py3-none-any.whl" \
    "flashinfer-jit-cache-sm80==${flashinfer_version}+cu130" \
    "flashinfer-jit-cache-sm90a==${flashinfer_version}+cu130"
"${VENV}/bin/pip" check
"${VENV}/bin/pip" install --no-cache-dir --no-deps --extra-index-url https://flashinfer.ai/whl/cu130/ \
    "flashinfer-jit-cache==${flashinfer_version}+cu130"
"${VENV}/bin/python" -c "import sys, flashinfer_jit_cache as m; found = {p.distribution for p in m.get_jit_cache_providers()}; missing = {'flashinfer-jit-cache-sm80', 'flashinfer-jit-cache-sm90a'} - found; sys.exit(m.__version__ != sys.argv[1] or bool(missing))" "${flashinfer_version}+cu130"
"${VENV}/bin/python" -c "import importlib.metadata as m, sys; v = m.version('vllm'); sys.exit(v != sys.argv[1])" "${release_version}"
"${VENV}/bin/hf" --help > /dev/null
ln -sf "${VENV}/bin/vllm" /usr/local/bin/vllm

mkdir -p "${INSTALL_DIR}"
cp "${FEATURE_DIR}"/start-vllm.sh "${FEATURE_DIR}"/resolve-model.sh "${FEATURE_DIR}"/available-models.sh \
    "${FEATURE_DIR}"/find-model-store.sh "${FEATURE_DIR}"/model-source.sh "${FEATURE_DIR}"/validate-model.sh \
    "${FEATURE_DIR}"/models.json "${FEATURE_DIR}"/vllm-release.json \
    "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}"/*.sh

# Where the server keeps its state at run time (start-vllm.sh): user-owned.
mkdir -p "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache" 2> /dev/null || true

echo "vllm-model installed: vLLM ${release_version} in ${VENV}, scripts in ${INSTALL_DIR}"
echo "Done!"
