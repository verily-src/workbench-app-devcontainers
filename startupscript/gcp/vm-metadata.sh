#!/bin/bash

# vm-metadata.sh

# Retrieves instance attributes set on the VM.

function get_metadata_value() {
 local metadata_path="${1}"
 curl --retry 5 -s -f \
   -H "Metadata-Flavor: Google" \
   "http://metadata/computeMetadata/v1/instance/attributes/${metadata_path}"
}
readonly -f get_metadata_value 
