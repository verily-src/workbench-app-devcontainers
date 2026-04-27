setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    load common
}

@test "python3" {
    run_in_container python3 --version
}

@test "python3: venv" {
    run_in_container 'python3 -c "import venv"'
}

@test "pip3" {
    run_in_container pip3 --version
}

@test "cromwell" {
    run_in_container cromwell --version
}

@test "nextflow" {
    run_in_container nextflow -v
}

@test "dsub" {
    run_in_container dsub -v
}

@test "bcftools" {
    run_in_container bcftools --version
}

@test "bedtools" {
    run_in_container bedtools --version
}

@test "bgenix" {
    run_in_container bgenix -help
}

@test "plink" {
    run_in_container plink --version
}

@test "plink2" {
    run_in_container plink2 --version
}

@test "samtools" {
    run_in_container samtools --version-only
}

@test "bgzip" {
    run_in_container bgzip --version
}

@test "tabix" {
    run_in_container tabix --version
}

@test "vcftools" {
    run_in_container vcftools --version
}

@test "vcftools: fill-an-ac" {
    run_in_container 'set +o pipefail; fill-an-ac -h 2>&1 | grep "Usage: fill-an-ac"'
}

@test "vcftools: fill-fs" {
    run_in_container 'set +o pipefail; fill-fs -h 2>&1 | grep "Usage: fill-fs"'
}

@test "regenie" {
    run_in_container regenie --version
}

@test "vep" {
    run_in_container vep --help
}

@test "vep: filter_vep" {
    run_in_container filter_vep --help
}

@test "vep: variant_recoder" {
    run_in_container variant_recoder --help
}

@test "vep: haplo" {
    run_in_container haplo --help
}

@test "python: google-cloud-storage" {
    run_in_container 'python3 -c "import google.cloud.storage"'
}

@test "python: ipykernel" {
    run_in_container 'python3 -c "import ipykernel"'
}

@test "python: ipywidgets" {
    run_in_container 'python3 -c "import ipywidgets"'
}

@test "python: jupyter" {
    run_in_container 'python3 -c "import jupyter"'
}

@test "python: openai" {
    run_in_container 'python3 -c "import openai"'
}

@test "python: matplotlib" {
    run_in_container 'python3 -c "import matplotlib"'
}

@test "python: numpy" {
    run_in_container 'python3 -c "import numpy"'
}

@test "python: plotly" {
    run_in_container 'python3 -c "import plotly"'
}

@test "python: pandas" {
    run_in_container 'python3 -c "import pandas"'
}

@test "python: seaborn" {
    run_in_container 'python3 -c "import seaborn"'
}

@test "python: scikit-learn" {
    run_in_container 'python3 -c "import sklearn"'
}

@test "python: scipy" {
    run_in_container 'python3 -c "import scipy"'
}

@test "python: tqdm" {
    run_in_container 'python3 -c "import tqdm"'
}
