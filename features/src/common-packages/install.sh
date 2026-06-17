#!/bin/bash
set -e

echo "Installing user-specified packages..."

# Install Python packages
if [ -n "${PYTHONPACKAGES}" ] && command -v pip &> /dev/null; then
    echo "Installing Python packages: ${PYTHONPACKAGES}"
    pip install --no-cache-dir ${PYTHONPACKAGES}
fi

# Install R packages
if [ -n "${RPACKAGES}" ] && command -v R &> /dev/null; then
    echo "Installing R packages: ${RPACKAGES}"
    R --quiet -e "install.packages(strsplit('${RPACKAGES}', ',')[[1]], repos='https://cran.rstudio.com/', quiet=TRUE)"
fi

echo "Package installation complete!"
