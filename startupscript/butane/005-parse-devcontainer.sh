#!/bin/bash

# parse-devcontainer.sh parses the devcontainer templates and sets template variables.
set -e

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <path/to/devcontainer>"
    exit 1
fi

readonly INPUT=$1
if [[ -d /home/core/devcontainer/startupscript ]]; then
    cp -r /home/core/devcontainer/startupscript "${INPUT}"/startupscript
fi
echo "replacing devcontainer.json templateOptions"
sed -i "s/\${templateOption:login}/false/g" "${INPUT}"/.devcontainer.json
sed -i "s/\${templateOption:cloud}/aws/g" "${INPUT}"/.devcontainer.json
