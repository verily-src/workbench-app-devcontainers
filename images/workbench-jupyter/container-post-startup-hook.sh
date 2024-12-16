#!/bin/bash

# container-post-startup-hook.sh is executed at the end of the Mikey `post-startup.sh` script.
# workbench-jupyter starts the Jupyter notebook server here so that JupyterLab picks up the
# correct environment variables set by the Mikey `post-startup.sh` script.

# Kill existing JupyterLab process to pick up new gcloud environment variables
# such that the GCP integration plugins work correctly.
pkill -f jupyter-lab
