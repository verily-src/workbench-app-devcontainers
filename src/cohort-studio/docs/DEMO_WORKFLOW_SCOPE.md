# OMOP and genetics workflow demo scope

## Recommendation

Use Cohort Studio's existing Workbench workflow path, not a new Jupyter app,
for the first runnable demo. Studio already exports the current dataset to an
S3 resource, submits a registered Workbench workflow, lists job status and
output location, and exposes lineage events. This is a real runner path in the
app. A compatible registered workflow is not identified in this repository;
check the workspace registry before treating the demo as runnable. Do not
submit a job until an owner confirms its workflow ID, CSV input contract, and
output bucket.

The repository has no Jupyter or data-science app launcher, and no code that
hands a Studio dataset or cohort to a notebook. A notebook would need a
separately available Workbench app, an S3 input handoff, and an output/lineage
path. It is a later option only if a suitable app already exists.

## What works today

- `GET /api/workflows/registry` lists workspace workflows through `wb workflow
  list`. The UI's **Run workflow** panel lets a user select a registered
  workflow and an output S3 resource.
- The panel can export the current dataset and filters as CSV to an input S3
  resource. `POST /api/datasets/{id}/export-cohort` returns the S3 URI and row
  count. For database-backed datasets it fetches at most `queries.ROW_CAP`
  (100,000) rows; keep the demo input below that limit and verify the returned
  row count.
- `POST /api/workflows/submit` invokes `wb workflow job run`. It accepts the
  workflow ID, output resource, and optional input bucket/path, column mapping,
  and row selection. The app does not inspect a workflow's schema or guarantee
  that the submitted job consumes the exported CSV.
- `GET /api/workflows` shows job status and output bucket/path. It does not
  list or preview files produced by a job. The output S3 resource can be
  opened separately through the normal datasource browser.
- The synthetic `genetics_demo` tables are already in the existing Aurora
  resource. Their planted pattern is fabricated: 500 people, 20 variants and
  10,000 dosage-2 genotype rows at the documented default size. The local
  browser fixture uses 100 people, 20 variants and 2,000 genotype rows, so
  its corresponding planted subset is 10 people and 200 rows. These values
  demonstrate data plumbing only; they are not scientific or clinical
  findings.
- Studio can join same-resource Aurora tables at database scope. The OMOP
  cohort builder can count and open a cohort, but an opened cohort is an
  in-memory dataset with the app row limit and no durable table source
  reference. Joining that result to full-source genetics tables therefore does
  not preserve a full-source cohort query. Do not describe such an export as a
  complete cohort unless its row count and cap are checked.

## Smallest practical demo

1. In Studio, build a same-Aurora join: `cms_synpuf_100k.person` →
   `genetics_demo.samples` on `person_id` → `genetics_demo.genotypes` on
   `sample_id` → `genetics_demo.variants` on `variant_id`.
2. Filter to `samples.demo_group = planted_demo_group`,
   `variants.demo_group = planted_demo_pattern`, and `dosage = 2`. Keep
   `person_id`, `sample_id`, `variant_id`, dosage, and the explicit
   `synthetic_*` fields. This yields the documented planted pattern before
   any optional OMOP condition-cohort restriction.
3. Export the filtered join as CSV to an existing input S3 resource. Check the
   returned URI and row count. Use a distinct demo prefix; do not overwrite
   source or import artifacts.
4. Submit a registered Workbench workflow that reads that one CSV and writes
   two small outputs to an existing output S3 resource:
   `variant_summary.csv` (variant ID, synthetic annotation, distinct people,
   samples, genotype rows, and dosage-2 rows) and `run_manifest.json` (input
   URI, input row count, workflow/run IDs, aggregation definition, and the
   synthetic-data notice).
5. Verify the job reaches a terminal status, read the output files through
   the existing S3 datasource, and compare all counts with direct Aurora SQL
   over the same filters. Report person count separately from genotype row
   count. Do not calculate association statistics or make treatment or
   disease-risk claims.

An optional second run can add a real OMOP condition cohort. Its expected
intersection with `genetics_demo` must be measured from the target Aurora
tables first; it will not in general equal the unfiltered 500-person/10,000-row
planted-pattern counts. Keep the exported result under 100,000 rows. The
current loaded-cohort-to-live-join boundary is a limit; if a complete,
large cohort is required, first add a server-side cohort predicate or durable
cohort source reference.

## Lineage and artifacts

Studio currently records separate `omop_cohort_opened`, `joined`,
`cohort_exported`, and `workflow_submitted` events. A join event records its
source datasets and join recipe. The CSV export event records its S3 URI and
row count. The submission event records workflow ID and run ID. These events
do not form an end-to-end lineage edge from the join to the input CSV, from
that CSV to the workflow run, or from the run to its output files. The
workflow list shows an output location but not its artifact inventory.

Minimum lineage work before calling this a traceable workflow demo:

- record the source dataset ID/reference and applied filters with the exported
  input artifact URI and row count;
- link the submitted run to that input artifact and record workflow ID,
  output bucket, and returned run ID;
- after completion, record the output URI(s) as artifacts parented by the run.

Do not imply that the current separate event log already proves these links.

## Validation gate and open constraints

- Confirm a registered workflow exists and accepts the CSV shape produced by
  the selected join. If none exists, the next smallest implementation is a
  minimal Python/Nextflow workflow registered through the existing Workbench
  workflow process; Studio has no workflow authoring or registration API.
- Confirm the selected input and output S3 resources are available to the app
  and workflow runner. This scope does not create buckets, deploy a workflow,
  submit a run, or change permissions.
- Validate the filtered CSV header, row count, and distinct-person count
  against direct Aurora SQL. Validate output counts against the same SQL.
- Check whether the workflow's output files are visible through the selected
  S3 datasource and whether the workflow reports a stable output path.
- Test lineage edges with one completed run before presenting the result as
  reproducible. Workflow status visibility alone is not artifact provenance.
- Keep synthetic-data labels visible in the input/output manifest and UI.
  `synthetic_gene`, `synthetic_consequence`, and planted group fields are
  fabricated values. Do not use them to make biological or clinical claims.

## Code and data references

- [Workbench workflow endpoints and lineage writes](../app/main.py)
- [Workflow registry, S3 CSV export, and job submission](../app/workflows.py)
- [Workflow form](../web/src/components/LaunchWorkflow.tsx) and
  [job status view](../web/src/components/WorkflowsView.tsx)
- [Synthetic genetics data and planted pattern](imports/GENETICS_DEMO.md)
- [OMOP cohort and join design constraints](architecture.md)
- [Workflow operation boundaries](AGENT_PLAN.md)
