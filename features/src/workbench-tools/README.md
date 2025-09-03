
# Workbench Tools (workbench-tools)

Installs common tools for Workbench Apps. Currently it only supports Debian-based systems (e.g. Ubuntu) on x86_64.

## Example Usage

```json
"features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/workbench-tools:1": {}
}
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | Cloud provider to install CLI tools for. If set to \"gcp\", installFromSource will default to true. | string | "" |
| installFromSource | Install tools that require building from source. This may take a long time. | boolean | false |

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


---

_Note: This file was auto-generated from the [devcontainer-feature.json](devcontainer-feature.json).  Add additional notes to a `NOTES.md`._
