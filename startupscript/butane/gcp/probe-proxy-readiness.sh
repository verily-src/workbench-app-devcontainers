#!/bin/bash
# probe-proxy-readiness.sh checks if the proxy is up and running.
# This script requires docker to be running on the VM.

set -e

if docker ps -q --filter "name=proxy-agent" | grep -q . && docker ps -q --filter "name=application-server" | grep -q .; then
    echo "Proxy is ready."
    /home/core/set_guest_attributes.sh "startup_script/status"
else
    echo "proxy-agent or application-server is not started"
    exit 1
fi
