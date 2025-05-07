#!/bin/bash
set -e

echo "Cloning repo into /workspace/verily1..."
git clone git@github.com:verily-src/verily1.git verily1

cd verily1
git checkout fhir-agent

# Install Python dependencies
pip install -r tools/mlinfra/langchain/app_demo/requirements.txt