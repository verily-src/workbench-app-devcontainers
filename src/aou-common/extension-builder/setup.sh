#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

# Disable some of the default jupyterlab extensions. We will override these with
# the aou-jupyterlab extension
jupyter labextension disable @jupyterlab/filebrowser-extension:download
jupyter labextension disable @jupyterlab/filebrowser-extension:open-browser-tab
jupyter labextension disable @jupyterlab/docmanager-extension:download
jupyter labextension disable @jupyterlab/docmanager-extension:open-browser-tab
jupyter labextension disable @jupyterlab/notebook-extension:export

/tmp/extensions/install.sh
