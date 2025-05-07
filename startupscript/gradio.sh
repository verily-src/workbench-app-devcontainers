#!/bin/bash
set -e

if [ ! -f /workspace/verily1/main.py ]; then
  echo "Cloning repo into /workspace/verily1..."
  git clone git@github.com:verily-src/verily1.git /workspace/verily1
else
  echo "Repo already exists at /workspace/verily1"
fi

cd workspace/verily1
git checkout fhir-agent

# Install Python dependencies
pip install -r tools/mlinfra/langchain/app_demo/requirements.txt