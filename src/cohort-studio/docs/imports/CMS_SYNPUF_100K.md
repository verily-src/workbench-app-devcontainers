# CMS SynPUF: authorized 100,000-person dev import

Status (2026-10-22): COMPLETE. SSM command `8c48e559-4d0f-4382-84b6-32577eebfc06` returned Success. All 24 tables and 121,444,089 rows committed to Aurora schema `cms_synpuf_100k`; exactly 100,000 distinct people. Live Studio HTTP detection returned cdm:true with this schema. Default cohort count is 90,085 with an observation period, total_persons 100,000. CDM version remains unknown (null), as intended. Do not rerun the loader.
User authorized a 100,000-person subset on 2026-10-21.

- Collection: https://workbench.verily.com/data-collections/cms-syn-puf
- Collection UUID from screenshot: cf656e3d-068d-4910-a295-eb3941223cc5.
- Source: `bigquery-public-data.cms_synthetic_patient_data_omop` (US).
- Target workspace: `bugbash-nextflowonaws` (dev).
- Target Aurora resource: `cohort-dash-db-20261005`.
- Proposed new schema: `cms_synpuf_100k`; do not replace existing schemas.
- Source metadata inspected with authenticated bq CLI. Public dataset description
  says updated 2019-10-18. Metadata row counts are inventory, not import validation.
- The collection project's `aou_static_prep_*` and `cmssynpuf_index_*` datasets
  contain preparation/index tables. They are not the canonical OMOP tables.
- Source has no `cdm_source` or `visit_occurrence`. Do not claim a verified CDM
  version or create false visit records. `procedure_dat` / `procedure_datetime`
  require explicit mapping to `procedure_date` / `procedure_datetime` expected
  by Studio, retaining source provenance. Validate all source column mappings.

## Selection and transfer plan

Choose distinct person IDs deterministically, then export their complete linked
clinical records. Do not independently LIMIT each clinical table. Keep required
vocabulary and ancestry for concept search and descendant matching. Cost records
need event-domain-aware joins to selected event IDs; preserve supporting provider,
care-site and location references. Record every included/excluded table explicitly.

Candidate selection (must check person uniqueness and source snapshot first):

```sql
SELECT DISTINCT person_id
FROM `bigquery-public-data.cms_synthetic_patient_data_omop.person`
WHERE person_id IS NOT NULL
ORDER BY FARM_FINGERPRINT(CAST(person_id AS STRING)), person_id
LIMIT 100000
```

Stream typed batches; use bounded temporary storage, resumable table loads and
row-count checks. Keep incomplete tables outside CDM detection until final
activation. Verify 100,000 distinct persons, event membership, vocabulary joins,
cohort counts and the Studio UI against Aurora before reporting success.
The current CSV loader is not suitable unchanged: it stamps CDM 5.4, can drop
unknown columns, and cannot read BigQuery directly.

## Verified access and execution

- AWS SSO refreshed. Studio VM `i-0e9d71494595f205c` is running and reachable
  through SSM. A real connection inside `application-server` verified database
  `cohort_dash_db_20261005`; only `public` and `information_schema` user-visible
  schemas existed before import. No existing CDM schema will be replaced.
- BigQuery jobs run in `vwb-dev-affable-olive-9580` (CMS SynPUF dev project).
  The collection project still lacks jobs.create; it is not the billing project.
- A real source cost-domain query returned Procedure: 637,854,415 and Drug:
  111,085,969 rows. Both domains are included by event ID for selected people.
- Export command: `uv run --no-project --python .venv/bin/python
  app/synpuf_export.py --output-dir /private/tmp/cohort-synpuf-100k-20261021`.
  Progress log: `/private/tmp/cohort-synpuf-export.log`.
- Export all 24 source tables: person-linked tables filtered by the deterministic
  sample, costs filtered by selected clinical event IDs, full support/vocabulary
  tables except concept_ancestor restricted to descendant concepts observed in
  selected clinical/person records. This ancestry subset supports descendant
  matching for imported records; it is not the complete vocabulary hierarchy.
- CSV.GZ files preserve source columns and types. Manifest records row counts and
  SHA-256 of compressed files. Null marker is `\N`; empty strings are retained.
- The new loader renames procedure_dat to procedure_date and retains original
  column mapping in import metadata. It creates a fresh schema, loads and checks
  it within one transaction, then commits. It does not assign a CDM version.

## Full-source inventory (not the subset)

24 tables, 2,117,607,589 rows, 142.47 GiB logical bytes before target indexes.
The exact schema and metadata are in `cms_synpuf_source_inventory.json`.

| Table | Rows | Logical GiB |
|---|---:|---:|
| care_site | 320,545 | 0.009 |
| concept | 3,902,588 | 0.496 |
| concept_ancestor | 118,150,608 | 3.521 |
| concept_class | 300 | 0.000 |
| concept_relationship | 26,727,250 | 1.160 |
| condition_era | 223,393,336 | 9.986 |
| condition_occurrence | 289,182,385 | 21.170 |
| cost | 748,940,384 | 61.300 |
| death | 107,644 | 0.003 |
| device_exposure | 4,465,485 | 0.328 |
| domain | 39 | 0.000 |
| dose_era | 122,262,518 | 6.376 |
| drug_era | 122,266,452 | 6.377 |
| drug_exposure | 126,048,050 | 9.894 |
| drug_strength | 2,415,413 | 0.127 |
| location | 3,185 | 0.000 |
| observation | 37,531,051 | 2.754 |
| observation_period | 2,098,515 | 0.078 |
| payer_plan_period | 7,789,512 | 0.345 |
| person | 2,326,856 | 0.197 |
| procedure_occurrence | 278,769,529 | 18.309 |
| provider | 905,492 | 0.034 |
| relationship | 410 | 0.000 |
| vocabulary | 42 | 0.000 |

## Validation and continuation

- Exporter and real database loader outcome tests: 10 passed. Disposable PostgreSQL
  is used only to test Aurora driver compatibility, not as application storage.
- Independent Codex (gpt-6-luna) and OpenCode (GLM max) reviews found no confirmed
  blocker. Review reports: `/tmp/cohort-synpuf-codex-review.txt` and
  `/tmp/cohort-synpuf-glm-final.jsonl`.
- Cursor agent CLI was installed at user request; review is pending CLI login and
  clarification of the requested model alias “et”. No Cursor verdict exists yet.
- Workspace S3 transfer was proven with the `nextflow_outputs` resource profile.
  Prefix: `s3://v0-saas-dev-us-east-1-workbench/nextflow_outputs-bugbash-nextflowonaws/_studio_imports/cms_synpuf_100k/20261021/`.
  Studio container download also succeeded. General developer-role S3 writes are
  denied; use Workbench resource profiles with the installed `wb` executable path.
- Continuation process `/tmp/cohort-synpuf-finish.py` is running. It waits for the
  final export manifest, validates local files, uploads completed files and the
  loader, then runs the atomic import through SSM on `i-0e9d71494595f205c`.
  It checks 100k total persons and the running app's HTTP CDM detection afterward.
  Log: `/tmp/cohort-synpuf-finish.log`; SSM ID and final result will appear at
  `/tmp/cohort-synpuf-load-command-id.txt` and `/tmp/cohort-synpuf-load-result.json`.
  Do not start a second loader or claim completion without the final result.
