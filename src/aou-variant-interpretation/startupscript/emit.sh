#!/bin/bash

# emit.sh
#
# Creates a bash function that can be used for emitting logging messages with a date/timestamp

function emit() {
 echo "$(date '+%Y-%m-%d %H:%M:%S') $*"
}
readonly -f emit
