#!/bin/bash

# Wait until main.py exists
while [ ! -f "/home/vscode/repos/verily1/tools/mlinfra/langchain/app_demo" ]; do
  echo "Waiting for app_demo subdir in verily1 repo..."
  sleep 1
done

# Start the Gradio app
echo "Starting app..."
cd /home/vscode/repos/verily1/tools/mlinfra/langchain/app_demo
pip install -r requirements.txt
python main.py --gradio_remote