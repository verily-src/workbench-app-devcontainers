#!/bin/bash

# Creates a function set_metadata. This is expected to be sourced in other scripts
# to set guest attributes on the GCE VM.

# Sets guest attributes on the GCE VM.
function set_metadata() {
    local key="$1"  
    local value="$2" 
    echo "Setting metadata ${key} to ${value}"
    curl -s -X PUT --data "${value}" \
        -H "Metadata-Flavor: Google" \
        "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f set_metadata
