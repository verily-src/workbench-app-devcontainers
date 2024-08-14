#!/usr/bin/env bash

set -e

echo "Starting Java installation..."

if type apk > /dev/null 2>&1; then
    echo "Running apk update..."
    apk update
    echo "Installing Java..."
    apk add --no-cache openjdk17-jdk
else
    echo "(Error) Unable to find a supported package manager."
    exit 1
fi

echo "Done!"