#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

# Define source and destination directories
readonly SOURCE_DIR="/home/shiny/workspace/"
readonly DEST_DIR="/srv/shiny-server/aws-cost-explorer/verily_cost"

# Define the function to check if a file with the same name and size exists in the destination
function file_needs_copy() {
    local source_file="$1"
    local filename
    filename="$(basename "${source_file}")"
    local dest_file="${DEST_DIR}/${filename}"

    # If destination file doesn't exist, needs copy
    if [[ ! -f "${dest_file}" ]]; then
        return 0
    fi

    # If files differ in size, needs copy
    local source_size
    local dest_size
    source_size=$(stat -c%s "${source_file}" 2>/dev/null || echo "0")
    dest_size=$(stat -c%s "${dest_file}" 2>/dev/null || echo "0")

    if [[ "${source_size}" != "${dest_size}" ]]; then
        return 0
    fi

    # File exists and is same size, no copy needed
    return 1
}
readonly -f file_needs_copy

# Copy a CSV file to the destination directory
function copy_csv_file() {
    local source_file="$1"
    local filename
    filename="$(basename "${source_file}")"

    echo "Copying ${filename} to ${DEST_DIR}..."
    cp "${source_file}" "${DEST_DIR}/${filename}"
    echo "Successfully copied ${filename}"
}
readonly -f copy_csv_file

# Define the function to perform the scanning
function scan_and_copy_csvs() {
    # Create destination directory if it doesn't exist
    mkdir -p "${DEST_DIR}"

    # Search for CSV files and copy if needed
    if [[ -d "${SOURCE_DIR}" ]]; then
        find "${SOURCE_DIR}" -type f -name '*.csv' 2>/dev/null | while read -r csv_file; do
            if file_needs_copy "${csv_file}"; then
                copy_csv_file "${csv_file}"
            else
                echo "File '$(basename "${csv_file}")' already exists in ${DEST_DIR} with same size."
            fi
        done
    else
        echo "Source directory ${SOURCE_DIR} does not exist yet."
    fi
}
readonly -f scan_and_copy_csvs

# Mount workspace resources if wb command is available
if command -v wb &> /dev/null; then
    wb resource mount || echo 'Resource mounting failed or not applicable.'
fi

# Infinite loop to continuously scan every 5 seconds
while true; do
    # Call the function to perform the scanning
    scan_and_copy_csvs

    # Sleep for 5 seconds before the next iteration
    sleep 5
done
