#!/bin/bash
cd "$(dirname "$0")" || exit
source test-utils.sh

readonly TEMPLATE_ID="$1"
readonly APPS_WITH_WORKBENCH_TOOLS=(
    "custom-workbench-jupyter-template"
    "jupyter-aou"
    "nemo_jupyter"
    "nemo_jupyter_aou"
    "r-analysis"
    "vscode"
    "workbench-jupyter-parabricks"
    "workbench-jupyter-parabricks-aou"
)

HAS_WORKBENCH_TOOLS="false"
for APP in "${APPS_WITH_WORKBENCH_TOOLS[@]}"; do
    if [[ "$APP" == "$TEMPLATE_ID" ]]; then
        HAS_WORKBENCH_TOOLS="true"
        break
    fi
done
readonly HAS_WORKBENCH_TOOLS


# Template specific tests
check "gcsfuse" gcsfuse -v
check "wb cli" wb version
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"

# The workbench-tools feature should install these
if [[ "$HAS_WORKBENCH_TOOLS" == "true" ]]; then
    check "python3" python3 --version
    check "pip3" pip3 --version
    if [[ "$TEMPLATE_ID" != "nemo_jupyter" ]] && [[ "$TEMPLATE_ID" != "nemo_jupyter_aou" ]]; then
        check "cromwell" cromwell --version
    fi
    check "nextflow" nextflow -v
    check "dsub" dsub -v
    check "bcftools" bcftools --version
    check "bedtools" bedtools --version
    check "bgenix" 'bgenix -help | head -n1'
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
    check "vep" 'vep --help | head -n10'
    check "vep: filter_vep" 'filter_vep --help > /dev/null'
    check "vep: variant_recoder" 'variant_recoder --help | head -n10'
    check "vep: haplo" 'haplo --help | head -n10'
fi

# Report result
reportResults
