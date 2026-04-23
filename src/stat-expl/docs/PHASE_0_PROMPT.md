# Phase 0 — Schema discovery

GCP architecture:
  Data project:  wb-spotless-eggplant-4340
  App project:   wb-rapid-apricot-2196

Step 1 — discover all datasets:
  Run: bq ls --format=json --project_id=wb-spotless-eggplant-4340
  Save to: src/stat-expl/docs/bq_datasets.json

Steps 2–5 — for EACH dataset found in Step 1:
  Run the four queries defined in src/stat-expl/docs/SPEC.md Phase 0 section.
  Replace DATASET_NAME with the actual dataset name each time.
  Save files as src/stat-expl/docs/bq_DATASETNAME_tables.json etc.
  Always use --project_id=wb-rapid-apricot-2196 on every bq command.

Rules:
  - Schema and metadata only. No SELECT on actual table data. No LIMIT queries.
  - If a query fails, note the error, save an empty file, and continue.
  - Do not infer or guess — only use what the queries return.

After all queries complete, consolidate into src/stat-expl/docs/schema.json
using the structure in SPEC.md. Then print this summary and stop:

  1. Datasets found inside wb-spotless-eggplant-4340
  2. Tables per dataset — name, assigned clinical domain, row count, last modified
  3. Total columns across all datasets
  4. Columns with descriptions vs columns without
  5. Partition columns found per dataset
  6. Any datasets or tables that failed — list with error
  7. Tables with 0 rows or suspicious metadata
  8. Columns you could not classify — list by dataset.table.column

Wait for review before starting Phase 1.
