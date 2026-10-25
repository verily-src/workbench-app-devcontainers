# OMOP + genetics + S3 + Nextflow demo

## Verified flow

On 2026-10-25, Cohort Studio selected 29,553 OMOP people with an observation
period, gender concept 8532, and birth year 1930–1950. The opened cohort contained
all 29,553 member IDs. Joining those exact members with synthetic genotypes for
SYN_VAR_0021 and the S3 dictionary produced 1,475 people. Studio exported all
1,475 rows and submitted `cohort-genetics-demo` through its normal API.

Workbench run: `ceea2bdc-50fa-4922-a1a3-53e2a3e2b3fe`.
HealthOmics run: `4806228`, completed successfully.
The earlier six-person fixture also completed and was reopened through the
live dashboard query API. Live browser clicks and model interpretation are
separate acceptance checks; API execution does not prove those steps.

## Run the demo

1. Select Aurora → `cohort-dash-db-20261005` → OMOP. Choose gender Female and
   birth years 1930–1950, keep observation periods required, then open the cohort.
2. In Join → SQL, create **Genetic inputs** using the query below.
3. Make Genetic inputs the join base. Inner join the opened OMOP cohort on
   `person_id`. Open S3 → `nextflow_resources` →
   `cohort-studio/demo-v1/variant_dictionary.csv`, and inner join it on `variant_id`.
   Accept the cross-source data scan. This join runs in DuckDB. Keep the six
   base-column names unchanged; dictionary columns are enrichment.
4. On the joined tab, choose Run workflow → **Cohort genetics demo**. Use
   `nextflow_params` for input and `nextflow_outputs` for output. Write CSV,
   then Submit job. A changed cohort/filter/path requires a fresh export.
5. Track the run under Workflows. After completion, select S3 →
   `nextflow_outputs`, then the run's output path, engine run ID, and `pubdir`.
   Load `carrier_summary.csv` into the dashboard.
6. Ask the configured assistant: “Sum the people column by carrier_status.
   Describe the birth-year strata and state that these genotypes are synthetic.
   Do not infer causation or clinical significance.”

```sql
SELECT p.person_id, s.sample_id, g.variant_id, g.dosage,
       p.gender_concept_id, p.year_of_birth
FROM genetics_demo.samples s
JOIN genetics_demo.genotypes g ON g.sample_id = s.sample_id
JOIN cms_synpuf_100k.person p ON p.person_id = s.person_id
WHERE g.variant_id = 'SYN_VAR_0021'
```

This query supplies genetics and demographics. The inner join to the opened
OMOP cohort applies the selected cohort membership; do not omit that join.

## Existing artifacts

All paths below are relative to the selected Workbench S3 resource.

| Resource | Path | Purpose |
| --- | --- | --- |
| nextflow_resources | cohort-studio/demo-v1/variant_dictionary.csv | Synthetic annotation mapping, keyed by variant_id |
| nextflow_params | cohort-studio/demo-inputs/omop-genetics-20261025.csv | Verified 1,475-person analysis input |
| nextflow_outputs | cohort-studio/demo-omop-20261025/cohort-genetics-omop-20261025/4806228/pubdir/carrier_summary.csv | Real-cohort aggregate results |
| nextflow_outputs | cohort-studio/demo-omop-20261025/cohort-genetics-omop-20261025/4806228/pubdir/run_manifest.json | Hashes, counts, synthetic notice and output locations |

For a quick replay, load the saved input CSV, choose the demo workflow, write
it to a new input path, and submit under a new job name.

## Result interpretation and limits

Carrier means synthetic dosage greater than zero. The summary groups people
by carrier status, gender and birth decade. Its rows are **strata**, not people:
sum `people` for population counts. The dictionary does not determine carrier
status. No clinical or causal conclusion is supported.

The six required input columns are `person_id`, `sample_id`, `variant_id`,
`dosage`, `gender_concept_id`, and `year_of_birth`. The workflow rejects duplicate
people/samples, mixed variants and invalid dosage. Studio rejects capped exports.
The opened cohort's row count must equal the counted cohort before this path is
used; the successful example verified that equality. Durable cohort snapshots
remain a separate feature.

The manifest has a distinct HealthOmics `engine_run_id`. Its Workbench run ID
and source-table fields are not inferred; the Workbench job/Studio lineage link
provides those separately. Keep the selected cohort spec with the demonstration.

Workflow source and offline packaging instructions:
[cohort-genetics-demo](../workflows/cohort-genetics-demo/README.md).
