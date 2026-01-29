#!/bin/bash
cd "$(dirname "$0")" || exit
source test-utils.sh

readonly TEMPLATE_ID="$1"
readonly TEST_USER="$2"
readonly HAS_WORKBENCH_TOOLS="$3"
readonly HAS_POSTGRES_CLIENT="$4"

function check() {
    check_user "${TEST_USER}" "$@"
}

# Template specific tests
check "gcsfuse" gcsfuse -v
check "wb cli" wb version
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"

# The workbench-tools feature should install these
if [[ "$HAS_WORKBENCH_TOOLS" == "true" ]]; then
    check "python3" python3 --version
    check "python3: venv" 'python3 -c "import venv"'
    check "pip3" pip3 --version
    if [[ "$TEMPLATE_ID" != "nemo_jupyter" ]] && [[ "$TEMPLATE_ID" != "nemo_jupyter_aou" ]]; then
        check "cromwell" cromwell --version
    fi
    check "nextflow" nextflow -v
    check "dsub" "which dsub && dsub -v"
    check "bcftools" bcftools --version
    check "bedtools" bedtools --version
    check "bgenix" "bgenix -help | head -n1"
    check "plink" plink --version
    check "plink2" plink2 --version
    check "samtools" samtools --version-only
    check "bgzip" bgzip --version
    check "tabix" tabix --version
    check "vcftools" vcftools --version
    # fill-an-ac -h returns 1, so grep the usage string instead
    check "vcftools: fill-an-ac" 'set +o pipefail; fill-an-ac -h 2>&1 | grep "Usage: fill-an-ac"'
    # fill-fs -h returns 1, so grep the usage string instead
    check "vcftools: fill-fs" 'set +o pipefail; fill-fs -h 2>&1 | grep "Usage: fill-fs"'
    check "regenie" regenie --version
    check "vep" "vep --help | head -n10"
    check "vep: filter_vep" "filter_vep --help > /dev/null"
    check "vep: variant_recoder" "variant_recoder --help | head -n10"
    check "vep: haplo" "haplo --help | head -n10"
    # Python packages (use conda python directly)
    check "python: google-cloud-storage" '/opt/workbench-tools/2/bin/python3 -c "import google.cloud.storage"'
    check "python: ipykernel" '/opt/workbench-tools/2/bin/python3 -c "import ipykernel"'
    check "python: ipywidgets" '/opt/workbench-tools/2/bin/python3 -c "import ipywidgets"'
    check "python: jupyter" '/opt/workbench-tools/2/bin/python3 -c "import jupyter"'
    check "python: openai" '/opt/workbench-tools/2/bin/python3 -c "import openai"'
    check "python: matplotlib" '/opt/workbench-tools/2/bin/python3 -c "import matplotlib"'
    check "python: numpy" '/opt/workbench-tools/2/bin/python3 -c "import numpy"'
    check "python: plotly" '/opt/workbench-tools/2/bin/python3 -c "import plotly"'
    check "python: pandas" '/opt/workbench-tools/2/bin/python3 -c "import pandas"'
    check "python: seaborn" '/opt/workbench-tools/2/bin/python3 -c "import seaborn"'
    check "python: scikit-learn" '/opt/workbench-tools/2/bin/python3 -c "import sklearn"'
    check "python: scipy" '/opt/workbench-tools/2/bin/python3 -c "import scipy"'
    check "python: tqdm" '/opt/workbench-tools/2/bin/python3 -c "import tqdm"'
fi

# The postgres-client feature should install these
if [[ "${HAS_POSTGRES_CLIENT}" == "true" ]]; then
    check "psql" psql --version
    check "pg_dump" pg_dump --version
    check "pg_restore" pg_restore --version
fi

# Report result
reportResults
