#!/bin/bash

# container-post-startup-hook.sh is executed at the end of the Mikey `post-startup.sh` script.
# workbench-jupyter starts the Jupyter notebook server here so that JupyterLab picks up the
# correct environment variables set by the Mikey `post-startup.sh` script.

# Kill existing JupyterLab processes
pkill -f jupyter-lab

# Start JupyterLab
cd /home/jupyter || exit 1
sudo -u jupyter bash -l -c "jupyter lab"
