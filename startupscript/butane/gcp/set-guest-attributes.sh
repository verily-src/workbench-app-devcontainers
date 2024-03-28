#!/bin/bash

# set-guest-attributes.sh sets guest attributes on the VM.

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <key> <value>"
    exit 1
fi
curl -s -X PUT --data "$2" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/$1"