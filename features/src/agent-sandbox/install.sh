#!/usr/bin/env bash

# install.sh installs the agent-sandbox feature: the openshell CLI, the agent-sandbox command
# and its policy files in /opt/agent-sandbox, and, in the broker role, sshd. See README.md.

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
readonly ROLE="${ROLE:-"app"}"
readonly OPENSHELL_VERSION="${OPENSHELLVERSION:-"0.1.4"}"
readonly OPENSHELL_SHA256="${OPENSHELLSHA256:-"2b65178e62e1ece1d90d482555e9f1f98ff0296e058409b33418104b6333df07"}"

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

readonly INSTALL_DIR="/opt/agent-sandbox"

FEATURE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly FEATURE_DIR

WORKDIR="$(mktemp -d)"
readonly WORKDIR

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

echo "Starting agent-sandbox installation (role: ${ROLE})..."

case "${ROLE}" in
    app|broker) ;;
    *) echo "Error: role must be app or broker, got '${ROLE}'."; exit 1 ;;
esac

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# The commands are bash with jq; harness.py needs PyYAML. The app side also needs ssh (the
# openssh-client package) to reach the broker; the broker needs sshd.
check_packages bash ca-certificates curl jq openssh-client python3 python3-yaml
if [[ "${ROLE}" == broker ]]; then
    check_packages openssh-server
fi

# The OpenShell CLI, checked against the pinned archive digest. Sandboxes run on the gateway
# container, not here; this container has no Docker socket.
if [[ "$(uname -m)" != x86_64 ]]; then
    echo "Error: OpenShell is installed for x86_64 only (got $(uname -m))."
    exit 1
fi
curl --retry 3 -fsSL \
    "https://github.com/NVIDIA/OpenShell/releases/download/v${OPENSHELL_VERSION}/openshell-x86_64-unknown-linux-musl.tar.gz" \
    -o "${WORKDIR}/openshell.tar.gz"
printf '%s  %s\n' "${OPENSHELL_SHA256}" "${WORKDIR}/openshell.tar.gz" | sha256sum -c -
tar -xzf "${WORKDIR}/openshell.tar.gz" -C /usr/local/bin openshell
OPENSHELL_TELEMETRY_ENABLED=false openshell --version

# The feature's files. harnesses/ is filled by harness features (opencode-harness), which
# install after this one; the first writes harnesses/default.
mkdir -p "${INSTALL_DIR}/harnesses"
cp "${FEATURE_DIR}/agent-sandbox.sh" "${FEATURE_DIR}/selftest.sh" "${FEATURE_DIR}/broker-client.sh" "${FEATURE_DIR}/harness.py" "${FEATURE_DIR}/tool-groups.yaml" "${INSTALL_DIR}/"
rm -rf "${INSTALL_DIR}/config" "${INSTALL_DIR}/broker" "${INSTALL_DIR}/sandbox"
cp -r "${FEATURE_DIR}/config" "${FEATURE_DIR}/broker" "${FEATURE_DIR}/sandbox" "${INSTALL_DIR}/"
chmod +x "${INSTALL_DIR}"/*.sh "${INSTALL_DIR}"/harness.py "${INSTALL_DIR}"/broker/*.sh "${INSTALL_DIR}"/sandbox/*.py
chmod 644 "${INSTALL_DIR}/broker/sshd_config"
ln -sf "${INSTALL_DIR}/agent-sandbox.sh" /usr/local/bin/agent-sandbox

if [[ "${ROLE}" == broker ]]; then
    # Check the sshd configuration now, against a throwaway host key; the real one is made at
    # start. sshd -t also wants the privilege-separation directory, which exists only at run time.
    mkdir -p /run/sshd
    ssh-keygen -q -t ed25519 -N '' -f "${WORKDIR}/check_key"
    sed "s#/etc/ssh/keys/ssh_host_ed25519_key#${WORKDIR}/check_key#" "${INSTALL_DIR}/broker/sshd_config" > "${WORKDIR}/sshd_check"
    /usr/sbin/sshd -t -f "${WORKDIR}/sshd_check"
fi

# Where the sandbox state is kept at run time: the user's.
mkdir -p "${USER_HOME_DIR}/openshell"
chown -R "${USERNAME}:" "${USER_HOME_DIR}/openshell" 2> /dev/null || true

echo "agent-sandbox installed in ${INSTALL_DIR} (openshell ${OPENSHELL_VERSION}, role ${ROLE})"
echo "Done!"
