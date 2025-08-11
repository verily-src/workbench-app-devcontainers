#!/bin/bash
# ==============================================================================
# Workbench Docker Credential Helper
#
# This must be landed in the application at ${PATH}/credential-helper-workbench
#
# This script implements the Docker credential helper protocol for scenarios
# where credentials are ONLY fetched dynamically and are never stored.
#
# It supports the full protocol, with active logic for 'get' and 'list'.
#   - get:    Retrieves credentials for a specific registry.
#   - list:   Dynamically enumerates all accessible registries.
#   - store:  Does nothing and exits successfully.
#   - erase:  Does nothing and exits successfully.
#
# Official Protocol Documentation:
#   https://docs.docker.com/reference/cli/docker/login/#credential-helper-protocol
#
# Dependencies:
#   - /home/core/wb.sh: The Workbench Docker wrapper script.
#   - jq: A lightweight and flexible command-line JSON processor.
#     (On Debian/Ubuntu: sudo apt-get install jq)
# ==============================================================================

set -euo pipefail

# Source the ECR repository helper functions
source '/home/core/docker-repositories.sh'

# --- Logic Functions ---

# Function to dynamically fetch credentials for a given registry.
# Arguments:
#   $1: server_url - The registry URL (e.g., my-registry.com)
get_credentials() {
    local server_url="${1}"

    # Extract hostname from URL (Docker sends full URL like https://registry.com/v2)
    local registry_hostname
    registry_hostname=$(echo "${server_url}" | sed -E 's|^https?://([^/]+).*|\1|')

    # Get the ECR login password for this registry hostname
    local password
    password="$(get_ecr_login_password_by_url "${registry_hostname}")" || {
        echo "Error: Failed to get credentials for registry ${registry_hostname}" >&2
        exit 1
    }

    # For ECR, the username is always "AWS"
    local username="AWS"

    # Use jq to safely construct the JSON output
    jq -n \
      --arg user "${username}" \
      --arg pass "${password}" \
      --arg url "${server_url}" \
      '{"Username": $user, "Secret": $pass, "ServerURL": $url}'
}

# Function to dynamically list all accessible registries.
list_registries() {
    # Get all ECR registries from Workbench and format as JSON object
    # mapping server URLs to usernames (always "AWS" for ECR)
    local registries_json="{}"
    
    while read -r registry_url _; do
        if [[ -n "${registry_url}" ]]; then
            registries_json=$(echo "${registries_json}" | jq --arg url "${registry_url}" '. + {($url): "AWS"}')
        fi
    done < <(get_ecr_registries || true)
    
    echo "${registries_json}"
}


# --- Main Logic ---

# The first argument from Docker is the command.
COMMAND="${1:-}"

case "${COMMAND}" in
    store)
        # 'docker login' calls this. In a get-only model, we do nothing.
        # The command must read from stdin to prevent the pipe from breaking,
        # but we discard the input.
        cat > /dev/null
        exit 0
        ;;

    get)
        # 'docker pull' or 'docker push' calls this command.
        # It reads the server URL from stdin.
        read -r server_url
        get_credentials "${server_url}"
        ;;

    erase)
        # 'docker logout' calls this. We do nothing.
        # Read from stdin to clear the pipe and exit successfully.
        cat > /dev/null
        exit 0
        ;;

    list)
        # This command lists all registries the current identity can access.
        list_registries
        ;;

    *)
        echo "Error: Invalid command '${COMMAND}'" >&2
        echo "Usage: $0 {store|get|erase|list}" >&2
        exit 1
        ;;
esac
