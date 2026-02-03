#!/bin/bash
# Script to extract Artifact Registry regions from image URLs in files and authenticate with docker
# Usage: ./docker-auth.sh <path> [default-regions]
#   path: subdirectory under /home/core/devcontainer (required)
#   default-regions: comma-separated list of regions to always include (defaults to us-central1)

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Validate required parameter
if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
    echo "Error: path parameter is required" >&2
    echo "Usage: $0 <path> [default-regions]" >&2
    exit 1
fi

DEVCONTAINER_PATH="/home/core/devcontainer/$1"

# Default regions to always include (comma-separated)
DEFAULT_REGIONS="${2:-us-central1}"

# Check if path exists and search for registries
REGISTRIES=""
if [ ! -d "$DEVCONTAINER_PATH" ]; then
    echo "Warning: Directory $DEVCONTAINER_PATH does not exist, skipping file search" >&2
else
    echo "Searching for Artifact Registry URLs in: $DEVCONTAINER_PATH" >&2

    # Find all image URLs matching *-docker.pkg.dev pattern
    # Extract unique registry hostnames and then get locations
    REGISTRIES=$(grep -r -h -o -E '[a-z0-9-]+-docker\.pkg\.dev/[^[:space:]"'\'']*' "$DEVCONTAINER_PATH" 2>/dev/null | \
        cut -d'/' -f1 | \
        sort -u)

    if [ -n "$REGISTRIES" ]; then
        echo "Found registries:" >&2
        echo "$REGISTRIES" >&2
    else
        echo "No Artifact Registry URLs found in $DEVCONTAINER_PATH" >&2
    fi
fi

# Extract locations from registries (remove -docker.pkg.dev suffix)
if [ -n "$REGISTRIES" ]; then
    LOCATIONS=$(echo "$REGISTRIES" | sed 's/-docker\.pkg\.dev$//' | sort -u)
else
    LOCATIONS=""
fi

# Append default regions (convert comma-separated to newline-separated)
DEFAULT_REGIONS_NEWLINE=$(echo "$DEFAULT_REGIONS" | tr ',' '\n')
LOCATIONS=$(echo -e "${LOCATIONS}\n${DEFAULT_REGIONS_NEWLINE}" | sort -u)

# Get access token from metadata server
echo "Getting access token..." >&2

# Temporarily disable xtrace to avoid logging sensitive credentials
set +o xtrace

TOKEN=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" -H "Metadata-Flavor: Google")
ACCESS=$(echo ${TOKEN} | grep -oP '(?<="access_token":")[^"]*')

# Login to each registry
echo "Logging into artifact registries..." >&2
echo "$LOCATIONS" | while read -r location; do
    [ -z "$location" ] && continue
    echo "  Logging into: ${location}-docker.pkg.dev" >&2
    docker login -u oauth2accesstoken -p "${ACCESS}" "https://${location}-docker.pkg.dev" > /dev/null 2>&1
done

# Re-enable xtrace
set -o xtrace

echo "Done!" >&2
