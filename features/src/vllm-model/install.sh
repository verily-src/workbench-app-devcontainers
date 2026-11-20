#!/usr/bin/env bash

# install.sh installs the vllm-model feature: a released vLLM in its own virtual environment
# (/opt/vllm), the CUDA 13.0 toolkit, and the start script in /opt/vllm-model. See README.md.

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

echo "Starting vllm-model installation..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi
if [[ "$(uname -m)" != x86_64 ]]; then
    echo "Error: the prebuilt FlashInfer kernels installed here are x86_64 only (got $(uname -m))."
    exit 1
fi

# gcc, g++ and python3-dev: torch.compile and Triton build small C helpers at start-up and need
# a C toolchain and the Python headers. jq: the scripts read JSON with it.
apt-get update -y
apt-get -y install --no-install-recommends ca-certificates curl gcc g++ jq python3 python3-dev python3-pip python3-venv

# The CUDA 13.0 toolkit, from NVIDIA's repository for this Ubuntu release. The recipe's Mamba
# state (float16, stochastic rounding) needs a FlashInfer kernel that no FlashInfer wheel carries,
# so FlashInfer compiles it on first start, and the compiler pip brings does not match the 13.0
# headers FlashInfer bundles. Toolkit only: the driver is the VM's.
# shellcheck source=/dev/null
release="$(. /etc/os-release && printf '%s%s' "${ID}" "${VERSION_ID//./}")"
curl --retry 3 -fsSL "https://developer.download.nvidia.com/compute/cuda/repos/${release}/x86_64/cuda-keyring_1.1-1_all.deb" \
    -o /tmp/cuda-keyring.deb
dpkg -i /tmp/cuda-keyring.deb
rm /tmp/cuda-keyring.deb
apt-get update -y
apt-get -y install --no-install-recommends cuda-toolkit-13-0
rm -rf /var/lib/apt/lists/*
/usr/local/cuda-13.0/bin/nvcc --version

# vLLM in its own virtual environment, pinned by vllm-release.json. The wheel brings PyTorch
# and the CUDA 13.0 libraries from pip. FlashInfer's prebuilt kernels: the cubin wheel, the
# flashinfer-jit-cache shim without its dependencies (the kernel sets for every architecture,
# 2.4 GB), and the H100 (sm90a) set. `pip check` would flag the shim's missing dependencies, so
# it runs before the shim. The version check reads package metadata: `vllm --version` probes
# for a GPU, and the image is built without one.
release_version="$(jq -r .version "${FEATURE_DIR}/vllm-release.json")"
flashinfer_version="$(jq -r .flashinfer_version "${FEATURE_DIR}/vllm-release.json")"
python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --no-cache-dir --upgrade pip
"${VENV}/bin/pip" install --no-cache-dir "vllm==${release_version}"
"${VENV}/bin/pip" install --no-cache-dir --extra-index-url https://flashinfer.ai/whl/cu130/ \
    "flashinfer-cubin @ https://github.com/flashinfer-ai/flashinfer/releases/download/v${flashinfer_version}/flashinfer_cubin-${flashinfer_version}-py3-none-any.whl" \
    "flashinfer-jit-cache-sm90a==${flashinfer_version}+cu130"
"${VENV}/bin/pip" check
"${VENV}/bin/pip" install --no-cache-dir --no-deps --extra-index-url https://flashinfer.ai/whl/cu130/ \
    "flashinfer-jit-cache==${flashinfer_version}+cu130"
"${VENV}/bin/python" -c "import sys, flashinfer_jit_cache as m; found = {p.distribution for p in m.get_jit_cache_providers()}; sys.exit(m.__version__ != sys.argv[1] or 'flashinfer-jit-cache-sm90a' not in found)" "${flashinfer_version}+cu130"
"${VENV}/bin/python" -c "import importlib.metadata as m, sys; v = (m.version('vllm'), m.version('flashinfer-python')); print('vllm', v[0], 'flashinfer', v[1]); sys.exit(v != tuple(sys.argv[1:]))" "${release_version}" "${flashinfer_version}"
"${VENV}/bin/hf" --help > /dev/null
ln -sf "${VENV}/bin/vllm" /usr/local/bin/vllm

mkdir -p "${INSTALL_DIR}"
cp "${FEATURE_DIR}"/start-vllm.sh "${FEATURE_DIR}"/vllm-release.json "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}"/*.sh
chmod -R a+rX "${INSTALL_DIR}"

# Where the server keeps its state at run time (start-vllm.sh): user-owned.
mkdir -p "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache"
chown -R "${USERNAME}:" "${USER_HOME_DIR}/.vllm" "${USER_HOME_DIR}/.cache" 2> /dev/null || true

echo "vllm-model installed: vLLM ${release_version} in ${VENV}, scripts in ${INSTALL_DIR}"
echo "Done!"
