#!/bin/bash
set -e

echo "Installing user-specified packages..."

# Install Python packages
if [ -n "${PYTHONPACKAGES}" ] && command -v pip &> /dev/null; then
    echo "Installing Python packages: ${PYTHONPACKAGES}"
    # PYTHONPACKAGES is a space-separated list and MUST word-split into
    # separate pip arguments — do not quote it (SC2086 is intentional here).
    # shellcheck disable=SC2086
    pip install --no-cache-dir ${PYTHONPACKAGES}
fi

# Install R packages
if [ -n "${RPACKAGES}" ] && command -v R &> /dev/null; then
    echo "Installing R packages: ${RPACKAGES}"
    R --quiet -e "install.packages(strsplit('${RPACKAGES}', ',')[[1]], repos='https://cran.rstudio.com/', quiet=TRUE)"
fi

echo "Package installation complete!"
