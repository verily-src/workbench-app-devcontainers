#!/bin/bash

# Docker ECR Repository Helper Functions
#
# This script provides functions to interact with AWS ECR repositories configured
# in Terra Workbench environments. It retrieves repository information and handles
# authentication for Docker operations.
#
# Public Functions:
#
#   get_ecr_registries()
#     Returns a list of unique ECR registry URLs and their associated repository IDs.
#     Output format: "registry_url repository_id" (one per line)
#     Example: "123456789.dkr.ecr.us-east-1.amazonaws.com my-repo"
#
#   get_ecr_login_password_by_url(registry_url)
#     Gets an ECR login password for the specified registry URL.
#     Returns the password that can be used with 'docker login --password-stdin'
#     Example: get_ecr_login_password_by_url "123456789.dkr.ecr.us-east-1.amazonaws.com"
#
# Usage Example:
#   source docker-repositories.sh
#   
#   # Get all registries
#   get_ecr_registries
#   
#   # Login to a specific registry
#   registry="123456789.dkr.ecr.us-east-1.amazonaws.com"
#   password=$(get_ecr_login_password_by_url "$registry")
#   echo "$password" | docker login --username AWS --password-stdin "$registry"
#
# Configuration
# Environment Variables:
#   WB_CLI_CMD - Path to wb.sh command (default: /opt/homebrew/bin/wb for macOS)

# Extract ECR registry URLs and associated repository IDs from Workbench resources
function get_ecr_registries() {
    local raw_resources
    raw_resources="$(/home/core/wb.sh resource list --format json)" || true

    # This awk command is used to discard any duplicate entries:
    #
    #   - $1 is the first field (registry URL)
    #   - seen[$1] creates an associative array indexed by URL
    #   - !seen[$1]++ means: if URL not seen before (seen[URL]=0, !0=true), print line and increment counter
    #   - If URL already seen (seen[URL]=1, !1=false), skip the line
    #
    # Result: only the first occurrence of each unique registry URL is kept

    echo "${raw_resources}" | jq -r '
        .[] | 
        if .resourceType == "AWS_ECR_EXTERNAL_REPOSITORY" then
            "\(.account).dkr.ecr.\(.region).amazonaws.com \(.id)"
        elif .resourceType == "AWS_ECR_EXTERNAL_REPOSITORY_REFERENCE" then
            "\(.referencedResource.account).dkr.ecr.\(.referencedResource.region).amazonaws.com \(.id)"
        else
            empty
        end
    ' | awk '!seen[$1]++' || true
}
readonly -f get_ecr_registries

# Get ECR login password for a registry URL
function get_ecr_login_password_by_url() {
    local registry_url="${1}"
    
    if [[ -z "${registry_url}" ]]; then
        echo "Error: Registry URL is required" >&2
        return 1
    fi
    
    # Get the repository ID for this registry URL
    local repo_id
    if ! repo_id="$(_get_ecr_repository_id "${registry_url}")"; then
        echo "Error: Could not find repository ID for registry URL ${registry_url}" >&2
        return 1
    fi
    
    if [[ -z "${repo_id}" ]]; then
        echo "Error: No repository found for registry URL ${registry_url}" >&2
        return 1
    fi
    
    # Get the login password using the repository ID
    _get_ecr_login_password "${repo_id}" "${registry_url}"
}
readonly -f get_ecr_login_password_by_url

# =============================================================================
# Internal Helper Functions
# =============================================================================

# Find the repository ID for a given ECR registry URL (internal helper)
function _get_ecr_repository_id() {
    local registry_url="${1}"

    if [[ -z "${registry_url}" ]]; then
        echo "Error: Registry URL is required" >&2
        return 1
    fi

    # Get the registry list and find matching URL
    get_ecr_registries | while read -r url id; do
        if [[ "${url}" == "${registry_url}" ]]; then
            echo "${id}"
            return 0
        fi
    done || true
}
readonly -f _get_ecr_repository_id

# Get ECR login password for a repository using its credentials (internal helper)
function _get_ecr_login_password() {
    local ecr_repo_id="${1}"
    local registry_url="${2}"  # Pass registry URL to avoid second lookup
    
    if [[ -z "${ecr_repo_id}" ]]; then
        echo "Error: ECR repository ID is required" >&2
        return 1
    fi
    
    if [[ -z "${registry_url}" ]]; then
        echo "Error: Registry URL is required" >&2
        return 1
    fi
    
    # Get credentials from wb.sh in credential_process JSON format
    local credentials
    credentials="$(/home/core/wb.sh resource credentials --name "${ecr_repo_id}" --scope READ_ONLY --format json)" || {
        echo "Error: Failed to get credentials for repository ${ecr_repo_id}" >&2
        return 1
    }
    
    # Extract credentials from JSON using jq
    local access_key_id
    local secret_access_key
    local session_token
    
    access_key_id="$(echo "${credentials}" | jq -r '.AccessKeyId')" || {
        echo "Error: Failed to parse AccessKeyId from credentials" >&2
        return 1
    }
    
    secret_access_key="$(echo "${credentials}" | jq -r '.SecretAccessKey')" || {
        echo "Error: Failed to parse SecretAccessKey from credentials" >&2
        return 1
    }
    
    session_token="$(echo "${credentials}" | jq -r '.SessionToken')" || {
        echo "Error: Failed to parse SessionToken from credentials" >&2
        return 1
    }
    
    # Extract region from registry URL (format: account.dkr.ecr.region.amazonaws.com)
    local region
    region="$(echo "${registry_url}" | cut -d'.' -f4)" || {
        echo "Error: Could not extract region from registry URL ${registry_url}" >&2
        return 1
    }
    
    # Run AWS CLI to get ECR login password
    docker run --rm \
        -e AWS_ACCESS_KEY_ID="${access_key_id}" \
        -e AWS_SECRET_ACCESS_KEY="${secret_access_key}" \
        -e AWS_SESSION_TOKEN="${session_token}" \
        amazon/aws-cli ecr get-login-password --region "${region}"
}
readonly -f _get_ecr_login_password
