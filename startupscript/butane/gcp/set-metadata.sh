#!/bin/bash

# Sets guest attributes on the GCE VM.
function set_metadata() {
  echo "Setting ${LAST_ACTIVE_KEY}"
  curl -s -X PUT --data "$2" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/$1"
}
readonly -f set_metadata
