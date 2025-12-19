#!/usr/bin/env bash

# install.sh
#
# Installs the PostgreSQL client in the devcontainer.
# This includes psql, pg_dump, and pg_restore tools.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly SQL_CLIENT_VERSION="${VERSION:-16}"

export DEBIAN_FRONTEND=noninteractive

function cleanup() {
    rm -rf /var/lib/apt/lists/*
}

trap 'cleanup' EXIT

function apt_get_update() {
    if [[ "$(find /var/lib/apt/lists/* | wc -l)" = "0" ]]; then
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

echo "Starting PostgreSQL client installation (version ${SQL_CLIENT_VERSION})..."

if ! type apt-get &>/dev/null; then
    echo "Error: unable to find a supported package manager."
    exit 1
fi

# Ensure required dependencies are installed
check_packages curl ca-certificates lsb-release gnupg

LSB_RELEASE="$(lsb_release -cs)"
readonly LSB_RELEASE

# Download the official PostgreSQL signing key
echo "Downloading PostgreSQL signing key..."
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    --output /usr/share/keyrings/postgresql-keyring.asc

# Add the PostgreSQL Apt repository to the sources list
echo "Adding PostgreSQL repository..."
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.asc] http://apt.postgresql.org/pub/repos/apt ${LSB_RELEASE}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list

# Update the package index
echo "Updating package index..."
apt-get update -qq

# Install the PostgreSQL client tools
echo "Installing postgresql-client-${SQL_CLIENT_VERSION}..."
apt-get install -y --no-install-recommends "postgresql-client-${SQL_CLIENT_VERSION}"

echo "Done!"
