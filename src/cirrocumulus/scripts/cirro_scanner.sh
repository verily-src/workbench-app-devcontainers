#!/bin/bash

# cirro_scanner.sh scans the mounted buckets to find cirro data. Creates a cirro dataset when *.zarr folder
# is found and is not yet in the existing cirro datasets.
# This script expects the user to be logged in to workbench CLI.

set -o errexit
set -o nounset
set -o pipefail

# Define the function to check for existing cirrocumulus datasets with the given path.
function matching_dataset_count() {
    local url="$1"
    curl -s localhost:3000/api/datasets | \
        jq -e --arg path "${url}" '.[] | select(.url == ${path})' | \
        wc -l
}
readonly -f dataset_exists

# Create a cirro dataset
function create_dataset() {
    local url="$1"
    local name
    name="$(basename "${url}")"
    curl -X POST -F "name=${name}" -F "url=${url}" localhost:3000/api/dataset
}
readonly -f create_dataset

# Define the function to perform the scanning
function scan_folders_and_create_datasets() {
    # Search for folders with name *.zarr and create cirro dataset if it doesn't exist
    find /root/workspace -type d -name '*.zarr' | while read -r folder; do
        if [[ "$(matching_dataset_count "${folder}")" -eq "0" ]]; then
            create_dataset "${folder}"
        else
            echo "Folder '${folder}' already exists in the cirrocumulus server dataset."
        fi
    done
}
readonly -f scan_folders_and_create_datasets

wb resource mount
# Infinite loop to continuously scan every 5 seconds
while true; do
    # Call the function to perform the scanning
    scan_folders_and_create_datasets

    # Sleep for 5 seconds before the next iteration
    sleep 5
done

