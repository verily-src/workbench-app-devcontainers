## Versions

- *bcftools==1.22
- bedtools: package manager version, currently 2.30.0
- *bgenix==1.1.7
- *htslib==1.22.1
- plink==20250615
- plink2==20250707
- *samtools==1.22.1
- *vcftools==0.1.17
- REGENIE==4.1 (both regenie and the _mkl version)
- *VEP==114.2

_*: These need to be built from source and will only be included if
`installFromSource` is set to `true` or `cloud` is set to `gcp`._

## dsub

On GCP, dsub is installed in its own venv (`/opt/workbench-tools/dsub`) because
it pins old Google libraries that conflict with other packages. Run
`dsub_activate` to activate it (for example, to install extra packages) and
`deactivate` to leave it.
