#!/bin/bash
cd "$(dirname "$0")" || exit
source test-utils.sh
sourceBashEnv

# Template specific tests
check "gcsfuse" which gcsfuse
check "wb cli" which wb
check "fuse.conf user_allow_other" grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"
check "cromwell" test -e "${CROMWELL_JAR}"
check "nextflow" which nextflow
check "dsub" which dsub

# The workbench-tools feature should install these
check "python3" which python3
check "bcftools" which bcftools
check "pip3" which pip3
check "bgenix" which bgenix
check "plink" which plink
check "plink2" which plink2
check "samtools" which samtools
check "bgzip" which bgzip
check "tabix" which tabix
check "vcftools: fill-an-ac" which fill-an-ac
check "vcftools: fill-fs" which fill-fs
check "regenie" which regenie
check "regenie_mkl" which regenie_mkl
check "vep" which vep
check "vep: filter_vep" which filter_vep
check "vep: variant_recoder" which variant_recoder
check "vep: haplo" which haplo

# Report result
reportResults
