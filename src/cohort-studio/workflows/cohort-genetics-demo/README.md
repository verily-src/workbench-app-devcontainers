# Synthetic variant summary workflow

This Nextflow workflow runs `analysis.py` on a cohort CSV and a synthetic
variant dictionary staged by Nextflow. It writes `carrier_summary.csv`,
`variant_dictionary.csv`, and `run_manifest.json` under a new output prefix.
The analysis input CSV must contain one row per matched person for one variant,
with this header:

```text
person_id,sample_id,variant_id,dosage,gender_concept_id,year_of_birth
```

The input CSV has exactly six columns. The separate dictionary CSV has exactly
`variant_id,gene_symbol,consequence,synthetic_notice`; its `variant_id` keys
must be unique and include the selected variant. The workflow copies the
dictionary to the output prefix so Studio can join it to the summary by
`variant_id`. Gene and consequence fields are annotations only and do not
affect carrier status.

The bundled `variant_dictionary.csv` is the default in local and HealthOmics
runs. Set `variant_dictionary` and `variant_dictionary_uri` to use a staged S3
dictionary instead. The manifest lists `source_resource` and `source_tables`
only when supplied; the workflow does not inspect Aurora.

The workflow rejects duplicate people or samples, mixed variant IDs, invalid
dosage values, duplicate dictionary keys, and an input whose matched-person
count exceeds `cohort_size`.
It defines a simulated carrier as dosage greater than zero. Missing or zero
gender/year values are grouped as `unknown`; year bands use decades. The output
has no person or sample identifiers. It makes no clinical or causal claim.

## Local run

Install Nextflow and use a local Python environment with Python 3 and Pydantic
2. For example, run from this directory with the Cohort Studio virtual
environment first in `PATH`:

```bash
PATH="../../.venv/bin:$PATH" nextflow run main.nf -profile local \
  --input input.csv \
  --variant_dictionary variant_dictionary.csv \
  --output_uri_prefix results/local-run \
  --cohort_size 6 \
  --input_uri file://input.csv
```

The `local` profile disables containers and uses the host Pydantic install. Use
a new output directory for each run; the analysis refuses to overwrite its
output files.

## Build the vendored runtime package

The HealthOmics task image has Python 3.10 but does not install Python packages
at run time. Build the pinned Linux x86_64 Python 3.10 dependencies before
registering or updating the workflow:

```bash
python3 build_bundle.py --force
```

The helper uses `uv pip install` with `requirements.txt` in a new directory
outside the repository, then writes a deterministic `vendor.zip` beside the
workflow. It prints the target path and checksums. Keep the generated archive
with the registered workflow source. Use `--target /private/tmp/<new-target>`
to choose an empty install directory. Replacing an existing archive requires
`--force`.

## HealthOmics run

Register this directory as a Nextflow workflow, then pass a parameter file with
one input S3 object and a unique output S3 prefix. For example:

```json
{
  "input": "s3://input-bucket/cohort/variant-0021.csv",
  "variant_dictionary": "s3://input-bucket/dictionaries/variant_dictionary.csv",
  "input_uri": "s3://input-bucket/cohort/variant-0021.csv",
  "variant_dictionary_uri": "s3://input-bucket/dictionaries/variant_dictionary.csv",
  "output_bucket": "output-bucket",
  "output_key": "cohort-genetics-demo/run-<unique-id>/<job-name>",
  "variant_id": "SYN_VAR_0021",
  "cohort_size": 5000,
  "source_tables": [
    "cms_synpuf_100k.person",
    "genetics_demo.samples",
    "genetics_demo.genotypes",
    "genetics_demo.variants"
  ],
  "source_resource": "<Workbench Aurora resource ID>",
  "workflow_id": "<registered workflow ID>",
  "run_id": "<returned run ID>"
}
```

Use the `healthomics` profile. The process publishes its three declared outputs
to `/mnt/workflow/pubdir`, the HealthOmics publication directory. Workbench
appends the job name to the submitted output path. The workflow uses that path
as `output_uri_prefix` and records each output as
`<output_uri_prefix>/<AWS_WORKFLOW_RUN_ID>/pubdir/<filename>`. It stores the
numeric task value in `execution.engine_run_id`; the optional `run_id` remains
the Workbench run ID. The workflow does not read Aurora or upload files itself.
Set `run_id` if the workflow runner exposes it
as a parameter; Workbench does not automatically inject its returned run ID
into the workflow process.

The workflow uses the existing, digest-pinned image
`535002863113.dkr.ecr.us-east-1.amazonaws.com/bench9232/scimilarity@sha256:330aa942ef83d78ec0ab55967303a3dc4401ad58271c93878f5d6229493e5361`.
It stages `vendor.zip`, extracts it to `vendor_runtime`, and sets `PYTHONPATH`
for the process, so it does not install packages at run time. The image is
Python 3.10.21; the process checks Pydantic before analysis. Include the
generated archive in the registered workflow package.

Local analysis boundary tests:

```bash
uv --cache-dir /tmp/uv-cache run --no-project \
  --python ../../.venv/bin/python -m pytest tests/test_analysis.py -q
```

The analysis boundary tests pass. The packaged Nextflow workflow and the
analysis in the pinned Linux image were also run locally. The HealthOmics
workflow was not registered or run, and no cloud resource was changed.

## Verified cloud execution

Workbench run `ceea2bdc-50fa-4922-a1a3-53e2a3e2b3fe` / HealthOmics `4806228`
completed with 1,475 records selected by the OMOP cohort and joined to synthetic
genotypes and an S3 dictionary. Six summary rows total 431 carriers and 1,044
noncarriers. The live app reopened the summary and verified manifest URIs.
See [demo runbook](../../docs/DEMO_OMOP_GENETICS.md) for the exact inputs and paths.
