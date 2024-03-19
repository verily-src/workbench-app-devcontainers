#!/bin/bash

# cirro_scanner.sh scans the mounted buckets to find cirro data. Creates a cirro dataset when *.zarr folder
# is found and is not yet in the existing cirro datasets.
set -o errexit
set -o nounset
set -o pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <true|false>"
  exit 1
fi

readonly LOG_IN="${1}"
if [[ "${LOG_IN}" == "false" ]]; then
  echo "user is not logged in"
  exit 0
fi

wb resource mount

# Define the function to check if folder path exists in the JSON array
function dataset_exists() {
    local url="$1"
    local array_json="$(curl -s localhost:3000/api/datasets)"
    local exists=$(echo "$array_json" | jq -e --arg path "$url" '.[] | select(.url == $path)' | wc -l)
    echo "$exists"
}
readonly -f dataset_exists

# Create a cirro dataset
create_dataset() {
    local url="$1"
    local name=$(basename "$url")
    curl -X POST -F "name=$name" -F "url=$url" localhost:3000/api/dataset
}
readonly -f create_dataset

# Define the function to perform the scanning
scan_folders_and_create_datasets() {
    # Search for folders with name *.zarr and create cirro dataset if it doesn't exist
    find /root/workspace -type d -name '*.zarr' | while read -r folder; do
        if [[ "$(dataset_exists "$folder")" -eq "0" ]]; then
            create_dataset "$folder"
        else
            echo "Folder '$folder' already exists in the cirro server dataset."
        fi
    done
}
readonly -f scan_folders_and_create_datasets

# Infinite loop to continuously scan every 5 seconds
while true; do
    # Call the function to perform the scanning
    scan_folders_and_create_datasets

    # Sleep for 5 seconds before the next iteration
    sleep 5
done

