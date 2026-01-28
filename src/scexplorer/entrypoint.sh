#!/bin/bash
set -e

echo "=== scExploreR Container Starting ==="

# Launch scExploreR
exec Rscript /usr/local/bin/launch-scexplorer.R
