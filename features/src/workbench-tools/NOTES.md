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

## Environments

Tools are installed in separate conda environments under
`/opt/workbench-tools`. To install extra packages into one, put its `python` and
`pip` first on the `PATH`:

```bash
env_activate /opt/workbench-tools/<environment>
env_deactivate  # undo
```

On GCP, dsub lives in its own environment because it pins old Google libraries.
Use `dsub_activate` and `dsub_deactivate` as shortcuts for it.
