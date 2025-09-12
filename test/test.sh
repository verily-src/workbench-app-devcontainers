#!/bin/bash
cd "$(dirname "$0")" || exit
source test-utils.sh
sourceBashEnv

readonly TEMPLATE_ID="$1"
readonly APPS_WITH_WORKBENCH_TOOLS=(
    "custom-workbench-jupyter-template"
    "jupyter-aou"
    "r-analysis"
    "vscode"
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
check "gcsfuse" which gcsfuse
check "wb cli" which wb
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"
if [[ "$TEMPLATE_ID" != "nemo_jupyter" ]] && [[ "$TEMPLATE_ID" != "nemo_jupyter_aou" ]]; then
    check "cromwell" test -e "${CROMWELL_JAR}"
fi
check "nextflow" which nextflow
check "dsub" which dsub

# The workbench-tools feature should install these
if [[ "$HAS_WORKBENCH_TOOLS" == "true" ]]; then
    # TODO(PHP-80766): Enable the disabled checks when caching is ready
    check "python3" which python3
    # check "bcftools" which bcftools
    check "pip3" which pip3
    # check "bgenix" which bgenix
    check "plink" which plink
    check "plink2" which plink2
    # check "samtools" which samtools
    # check "bgzip" which bgzip
    # check "tabix" which tabix
    # check "vcftools: fill-an-ac" which fill-an-ac
    # check "vcftools: fill-fs" which fill-fs
    check "regenie" which regenie
    check "regenie_mkl" which regenie_mkl
    # check "vep" which vep
    # check "vep: filter_vep" which filter_vep
    # check "vep: variant_recoder" which variant_recoder
    # check "vep: haplo" which haplo
fi

# Report result
reportResults
