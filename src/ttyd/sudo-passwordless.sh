#!/bin/bash

# This script is used to set up passwordless sudo for the core user on the VM.
# It requires to be run with root priviledges and USER_NAME to be set in the environment.
# It is typically called from post-startup.sh.

USER_NAME="${1}"

if [[ -z "${USER_NAME}" ]]; then
  echo "Usage: $0 <username>"
  exit 1
fi

sudoers_file="/etc/sudoers"
sudoers_d_file="/etc/sudoers.d/${USER_NAME}"

# Make sure user exists
if ! id "${USER_NAME}" &>/dev/null; then
  echo "User ${USER_NAME} does not exist."
  exit 1
fi

# Check if there's an old rule in the main sudoers file that requires a password
if grep -q "^${USER_NAME} ALL=(ALL:ALL) ALL" "${sudoers_file}"; then
  echo "Found password-requiring rule for ${USER_NAME} in /etc/sudoers. Commenting it out."
  
  # Comment out the old rule in /etc/sudoers
  sed -i "s/^${USER_NAME} ALL=(ALL:ALL) ALL/# ${USER_NAME} ALL=(ALL:ALL) ALL/" "${sudoers_file}"
fi

echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" > "${sudoers_d_file}"
chmod 440 "${sudoers_d_file}"

echo "User ${USER_NAME} has been given passwordless sudo access."
