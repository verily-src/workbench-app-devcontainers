#!/usr/bin/env bash

# setup-user.sh
# This script creates or updates a non-root user with sudo access.

# If username is not set, set to the provided feature option `USER`
# Defaults to `automatic`.
USERNAME="${USERNAME:-"${USER:-"automatic"}"}"

# Automatically set the UID/GID to match the non-root user.
readonly USER_GID="automatic"
readonly USER_UID="automatic"

# Create or update a non-root user to match UID/GID.
group_name="${USERNAME}"
if id -u "${USERNAME}" > /dev/null 2>&1; then
    # User exists, update if needed
    if [ "${USER_GID}" != "automatic" ] && [ "$USER_GID" != "$(id -g "$USERNAME")" ]; then
        group_name="$(id -gn "$USERNAME")"
        groupmod --gid $USER_GID "${group_name}"
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
fi

# Add add sudo support for non-root user
if [ "${USERNAME}" != "root" ] && [ "${EXISTING_NON_ROOT_USER}" != "${USERNAME}" ]; then
    echo "$USERNAME" ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/"$USERNAME"
    chmod 0440 /etc/sudoers.d/"$USERNAME"
    EXISTING_NON_ROOT_USER="${USERNAME}"
fi

if [ "${USERNAME}" = "root" ]; then
    user_home="/root"
fi
# Check if user already has a home directory other than /home/${USERNAME}
if [ "/home/${USERNAME}" != "$(getent passwd "${USERNAME}" | cut -d: -f6)" ]; then
    user_home=$( getent passwd "${USERNAME}" | cut -d: -f6 )
else
    user_home="/home/${USERNAME}"
    if [ ! -d "${user_home}" ]; then
        mkdir -p "${user_home}"
        chown "${USERNAME}:${group_name} ${user_home}"
    fi
fi

# Restore user .bashrc / .profile / .zshrc defaults from skeleton file if it doesn't exist or is empty
possible_rc_files=( ".bashrc" ".profile" )
for rc_file in "${possible_rc_files[@]}"; do
    if [ -f "/etc/skel/${rc_file}" ]; then
        if [ ! -e "${user_home}/${rc_file}" ] || [ ! -s "${user_home}/${rc_file}" ]; then
            cp "/etc/skel/${rc_file}" "${user_home}/${rc_file}"
            chown "${USERNAME}:${group_name} ${user_home}/${rc_file}"
        fi
    fi
done

# Ensure config directory
user_config_dir="${user_home}/.config"
if [ ! -d "${user_config_dir}" ]; then
    mkdir -p "${user_config_dir}"
    chown "${USERNAME}:${group_name} ${user_config_dir}"
fi

echo "Done!"
