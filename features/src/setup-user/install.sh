#!/usr/bin/env bash

# setup-user.sh
# This script creates or updates a non-root user with sudo access.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# If username is not set, set to the provided feature option `USER`
# Defaults to `automatic`.
USERNAME="${USERNAME:-"${USER:-"automatic"}"}"

# Automatically set the UID/GID to match the non-root user.
readonly USER_GID="automatic"
readonly USER_UID="automatic"

# Create or update a non-root user to match UID/GID.
USER_GROUP_NAME="${USERNAME}"
if id -u "${USERNAME}" > /dev/null 2>&1; then
    # User exists, update if needed
    if [ "${USER_GID}" != "automatic" ] && [ "$USER_GID" != "$(id -g "$USERNAME")" ]; then
        USER_GROUP_NAME="$(id -gn "$USERNAME")"
        groupmod --gid $USER_GID "${USER_GROUP_NAME}"
        usermod --gid $USER_GID "$USERNAME"
    fi
    if [ "${USER_UID}" != "automatic" ] && [ "$USER_UID" != "$(id -u "$USERNAME")" ]; then
        usermod --uid $USER_UID "$USERNAME"
    fi
else
    # Create user
    if [ "${USER_GID}" = "automatic" ]; then
        groupadd "$USERNAME"
    else
        groupadd --gid $USER_GID "$USERNAME"
    fi
    if [ "${USER_UID}" = "automatic" ]; then
        useradd -s /bin/bash --gid "$USERNAME" -m "$USERNAME"
    else
        useradd -s /bin/bash --uid $USER_UID --gid "$USERNAME" -m "$USERNAME"
    fi
    passwd -d "$USERNAME"
fi

# Add add sudo support for non-root user
if [ "${USERNAME}" != "root" ]; then
    # Ensure the sudoers.d directory exists
    if [ ! -d /etc/sudoers.d ]; then
        mkdir -p /etc/sudoers.d
        chmod 0755 /etc/sudoers.d
    fi
    echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME"
    chmod 0440 /etc/sudoers.d/"$USERNAME"
fi

# Set user_home based on USERNAME
USER_HOME_DIR=$(getent passwd "${USERNAME}" | cut -d: -f6)

# If USERNAME is root, set USER_HOME_DIR to /root
if [ "${USERNAME}" = "root" ]; then
    USER_HOME_DIR="/root"
fi

# Check if the home directory exists, and create it if necessary
if [ ! -d "${USER_HOME_DIR}" ]; then
    mkdir -p "${USER_HOME_DIR}"
    chown "${USERNAME}:${USER_GROUP_NAME}" "${USER_HOME_DIR}"
fi

# Restore user .bashrc / .profile / .zshrc defaults from skeleton file if it doesn't exist or is empty
possible_rc_files=( ".bashrc" ".profile" )
for rc_file in "${possible_rc_files[@]}"; do
    if [ -f "/etc/skel/${rc_file}" ]; then
        if [ ! -e "${USER_HOME_DIR}/${rc_file}" ] || [ ! -s "${USER_HOME_DIR}/${rc_file}" ]; then
            cp "/etc/skel/${rc_file}" "${USER_HOME_DIR}/${rc_file}"
            chown "${USERNAME}:${USER_GROUP_NAME}" "${USER_HOME_DIR}/${rc_file}"
        fi
    fi
done

# Ensure config directory
readonly USER_CONFIG_DIR="${USER_HOME_DIR}/.config"
if [ ! -d "${USER_CONFIG_DIR}" ]; then
    mkdir -p "${USER_CONFIG_DIR}"
    chown "${USERNAME}:${USER_GROUP_NAME}" "${USER_CONFIG_DIR}"
fi

echo "Done!"
