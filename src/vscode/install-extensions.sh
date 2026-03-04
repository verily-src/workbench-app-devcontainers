#!/bin/bash
# Install VSCode extensions after code-server is ready
# Usage: ./install-extensions.sh extension1 extension2 extension3

# Wait for code-server to be ready
until su - abc -c 'code-server --list-extensions' &> /dev/null; do
    sleep 1
done

# Install each extension
for extension in "$@"; do
    su - abc -c "code-server --install-extension $extension"
done
