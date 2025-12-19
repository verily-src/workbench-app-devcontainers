#!/bin/bash

# install-postgres-client.bash
#
# Installs or upgrades the PostgreSQL client in the app container.
#

readonly SQL_CLIENT_VERSION="16"

LSB_RELEASE="$(lsb_release -cs)"
readonly LSB_RELEASE

# 1. Download the official PostgreSQL signing key
# This ensures the authenticity of the packages we are about to install.
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    --output /usr/share/keyrings/postgresql-keyring.asc

# 2. Add the PostgreSQL Apt repository to the sources list
echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.asc] http://apt.postgresql.org/pub/repos/apt ${LSB_RELEASE}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list

# 3. Update the package index
# This refreshes the list of available packages from the newly added repository.
apt-get update -qq

# 4. Install the correct version of client tools
# This includes psql, pg_dump, and pg_restore.
apt-get install -y "postgresql-client-${SQL_CLIENT_VERSION}"
