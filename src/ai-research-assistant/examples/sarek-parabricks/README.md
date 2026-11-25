# nf-core/sarek with Parabricks, as a registered workflow

This is an example of an ordinary registered workflow run through the AI Research Assistant. It
shows nf-core/sarek 3.11.0 calling variants with NVIDIA Parabricks DeepVariant on Google Batch
GPUs. The assistant runs it with the Workbench workflow tools (`workflow_job_run`), and the
person approves the run. Nothing about it is built into the image: the assistant builds the
samplesheet and params file from the workspace's data with its own Python, and the files here
configure the workflow's GPU machines.

## Register the workflow

Register it with `wb workflow create --workflow-type=NEXTFLOW` (or the `workflow_create` tool
with `workflowType: NEXTFLOW`), from a copy of nf-core/sarek 3.11.0 kept in a workspace bucket.

The copy needs one change, the one `config/nfcore_custom.config` describes for
`PARABRICKS_HAPLOTYPECALLER`: the T4 has 16 GB and Parabricks HaplotypeCaller's defaults need at
least 18 GB (Parabricks 4.7.1 installation requirements), so the process takes
`ext.pb_extra_args` (`--htvc-low-memory`) in `conf/modules/parabricks_haplotypecaller.config`
of the pinned sarek copy.

## Configure

Upload `config/` to a folder of a workspace bucket. The params file sets `custom_config_base`
to `/mnt/disks/params/<that folder>/config`, because Workbench mounts the params file's bucket
on the Nextflow head node and accepts only a profile and a params file, not extra `-c` configs.
Run with the profile `gpu`, which `config/nfcore_custom.config` defines: every Parabricks
module in sarek carries the label `process_gpu`.

## Inputs

The samplesheet, for CRAMs, has the columns `patient,sex,status,sample,cram,crai`: one row per
sample, `status` 0 for a normal sample, `sex` as `XX`, `XY` or `NA`, and `cram` and `crai` as
`gs://` URLs.

The params file:

```yaml
input: gs://<bucket>/<folder>/samplesheet.csv
step: variant_calling
tools: parabricks_deepvariant
intervals: gs://<bucket>/<reference folder>/target_regions.bed
outdir: gs://<bucket>/<folder>/results
igenomes_ignore: true
fasta: gs://<bucket>/<reference folder>/<reference>.fasta
fasta_fai: gs://<bucket>/<reference folder>/<reference>.fasta.fai
dict: gs://<bucket>/<reference folder>/<reference>.dict
custom_config_base: /mnt/disks/params/<folder>/config
```

A workspace can keep a filled-in copy of this file, with placeholders for `input` and `outdir`,
beside `config/`: `sarek-parabricks/params-template.yaml` and `sarek-parabricks/config/` in the
output bucket, with `custom_config_base: /mnt/disks/params/sarek-parabricks/config`. A request
that names the template saves the agent from reading sarek's parameter schema
(`examples/ehr-genomics-chips.yaml` in the assistant UI does).

`intervals` selects the target regions (`target_regions.bed`, about an hour for a run) or the
whole genome (`primary_autosomes_XY.bed`, chr1-22, X and Y, about two hours).

## Run

Call `workflow_job_run` with `profile: gpu`, `paramsFileBucketId` and `paramsFilePath` (the
bucket resource's ID and the params file's path in it) and `outputBucketId`.

## Needs

- One T4 of GPU quota per sample, in the workspace's region.
- The reference and intervals files in a bucket the workflow can read.

## Known limitations

- The GPU type (T4) is fixed by `config/nfcore_custom.config`.
- The region follows the workspace: Workbench pins Google Batch to it, and its configuration is
  read after this one, so it cannot be overridden here.
