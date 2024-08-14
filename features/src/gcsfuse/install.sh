#!/usr/bin/env bash

set -e

echo "Starting GCS Fuse installation..."

apk update
apk add --no-cache fuse git go

export GOROOT=/usr/lib/go
export GOPATH=/go
mkdir -p ${GOPATH}/src ${GOPATH}/bin

go install github.com/googlecloudplatform/gcsfuse/v2@master
cp ${GOPATH}/bin/gcsfuse /usr/bin/gcsfuse

echo "GCS Fuse installation complete!"