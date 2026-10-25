# OMOP and synthetic genetics demo

## Scope

Demonstrate a descriptive comparison of simulated carriers and noncarriers for
one synthetic variant within a selected OMOP cohort. Preserve that cohort's
exact membership through the genetics join, analyze the intersecting people,
return aggregate results through S3, reopen them in Cohort Studio, and ask the
dataset assistant to summarize the displayed counts.

The genotype values and annotations are fabricated. They are linked to
`cms_synpuf_100k.person` only to demonstrate data plumbing. A result must not
be described as a genetic, clinical, or causal finding.

## What is implemented

- The OMOP Builder detects the CDM, searches concepts, counts cohorts against
  the database, shows attrition and demographic summaries, and opens a person
  dataset. Cohort counts cover the database. Opened cohorts are limited to
  100,000 rows and do not keep a live cohort query. An opened cohort is not a
  durable membership source for the genetics join. Treat this as a blocking
  gap: the exact cohort member IDs must be preserved before the join.
- The `genetics_demo` schema is present in the existing Aurora database. It
  contains 5,000 samples, 200 synthetic variants, and 1,000,000 genotypes.
  Each sample links to one OMOP person. See
  [GENETICS_DEMO.md](imports/GENETICS_DEMO.md) for verified import details.
- Cohort Studio can join same-resource Aurora tables and apply dashboard
  filters. The current S3 CSV export has a 100,000-row limit. Export only the
  selected variant after joining to the preserved cohort membership.
- Studio can open tabular files from an S3 source. It can display Workbench
  workflow status and submit registered workflows. These features do not
  create or launch a Jupyter app.
- The assistant can query a dataset, aggregate columns, update filters, and
  add charts. It needs a configured provider. The current live deployment has
  no configured inference key, so live interpretation is not verified.

## Gaps to close for the requested path

- This repository has no Jupyter launcher, notebook handoff, notebook
  execution, or notebook-to-S3 result upload. `workbench_apps.py` only lists
  app metadata for the cohort assistant; it cannot open or change an app.
- The workspace must have an available Jupyter app and a permitted way for
  that app to read the chosen input S3 object and write a separate output
  prefix. Confirm the app and access with its owner. Do not submit a job or
  change permissions as part of this scope.
- No registered workflow has been verified against the CSV contract below.
  Preferred automation is a registered Workbench workflow that consumes the
  input CSV and writes the summary and manifest to S3. Studio can submit such
  a workflow and show its status, but an owner must verify its registration,
  CSV contract, and output prefix first.
- The human-run Jupyter path is separate: a user opens an available Workbench
  Jupyter app, reads the input CSV, and writes both output artifacts to S3.
  Studio has no notebook launcher or notebook handoff. Confirm that the app
  exists and has access before presenting this path as runnable.
- Lineage events currently record joins, S3 exports, and workflow submissions
  separately. They do not link the input object to a notebook run or its
  outputs. Keep a run manifest with the artifacts until that lineage is wired.
- A provider key and a successful chat round-trip are required before
  presenting the final chat step as verified.

## Analysis definition

Use variant `SYN_VAR_0021`, the first non-planted variant. Define a simulated
carrier as dosage greater than zero; define a noncarrier as dosage zero. Keep
the carrier definition in the manifest. Do not infer carrier status from the
fabricated gene or consequence labels.

Build and count the chosen OMOP cohort in the OMOP Builder. Preserve the
normalized cohort spec and exact member IDs in a queryable source or an
explicit persisted membership snapshot. This storage step is not implemented
by the current cohort-open endpoint. Do not replace the selected cohort with
the full `person` table; that changes the question. The cohort source must
retain `person_id` and the demographics needed for the analysis, or allow a
join back to `cms_synpuf_100k.person`.

Join the preserved membership to these same-resource tables:

| Left source | Right source | Join key |
| --- | --- | --- |
| Cohort membership | `genetics_demo.samples` | `person_id` |
| joined result | `genetics_demo.genotypes` | `sample_id` |
| joined result | `genetics_demo.variants` | `variant_id` |
| joined result, if membership lacks demographics | `cms_synpuf_100k.person` | `person_id` |

Filter `variants.variant_id` to `SYN_VAR_0021`. Export these columns as the
analysis input: `person_id`, `sample_id`, `variant_id`, `dosage`,
`gender_concept_id`, and `year_of_birth`. `person_id` is needed to check
distinct people; the output summary must not contain person-level identifiers.
The input row count is the measured intersection of the selected cohort with
`genetics_demo.samples`, not a fixed 5,000. Record cohort size, matched people,
and unmatched cohort members separately.

In the workflow or Jupyter app, derive `carrier_status` from dosage, group by
status, gender, and birth-year band, and calculate people and the share within
each carrier group. Keep missing gender and birth year in explicit unknown
groups. Do not run a significance test or make outcome, treatment, or risk
claims. The genotype was assigned by the demo generator and has no biological
relationship to the OMOP records.

## Artifact contract

Write both artifacts to a new, unique S3 output prefix. Do not overwrite the
genetics import or source files.

`carrier_summary.csv` has one row per status/gender/birth-year band and these
columns:

`variant_id, carrier_status, gender_concept_id, birth_year_band, people, share_within_status, synthetic_notice`

`run_manifest.json` records the input S3 URI and row count, source resource and
tables, variant ID, carrier definition, output URIs, execution provenance, and
this notice: “Synthetic genotype values and annotations are for
workflow demonstration only; no clinical or causal interpretation.”
For the registered workflow path, record the workflow and returned run IDs.
For the human Jupyter path, record the notebook path or ID and execution time;
there is no Workbench workflow run ID for a manual notebook session.
Define `share_within_status` as stratum people divided by the matched-person
count for that carrier status.

Open `carrier_summary.csv` from its S3 source in Studio. Add a chart of people
by `carrier_status`, with gender or birth-year band as the breakdown. Ask chat
to report the group counts and explain the synthetic-data limit. The assistant
must ground counts in the opened summary and repeat that this is not a
clinical association result.

## Acceptance checks

1. OMOP Builder detects `cms_synpuf_100k`; record the database cohort count
   separately from any capped open dataset.
2. The persisted membership matches the OMOP Builder's selected cohort count.
   The joined, variant-filtered input row count equals the measured cohort /
   genetics intersection, with one row per distinct matched `person_id`.
   Every row has one sample, one genotype for the selected variant, and a
   matching OMOP person. Report unmatched cohort members. Read the input back
   from S3 and check its header and row count.
3. Carrier and noncarrier counts, computed from the input, sum to the measured
   matched-person count. Stratified `people` counts sum back to each status
   total. Do not hard-code the intersection or random carrier count.
4. The output CSV contains no person or sample identifiers. The manifest
   records the input/output URIs, run ID, analysis definition, and synthetic
   notice.
5. Studio opens the result CSV from the output prefix, displays all rows, and
   plots the group counts. Chat reports the values shown by the dataset tools
   and includes the synthetic-data limit.
6. A reviewer can follow the manifest from the input object to the run and
   output objects. Until lineage edges are implemented, the manifest is the
   trace record.

## References

- [Existing workflow demo scope](DEMO_WORKFLOW_SCOPE.md)
- [Synthetic genetics import](imports/GENETICS_DEMO.md)
- [OMOP cohort API and limits](../app/omop.py)
- [Workbench workflow and S3 operations](../app/workflows.py)
- [Dataset assistant tools](../app/agent.py)
- [Workbench app listing](../app/workbench_apps.py)
