# Cohort Explorer -- Execution Plan (v3)

Custom Workbench app for no-code cohort exploration of GTEx V8 data. POC for a partner demo. Replaces the v2 plan with corrections based on actual TSV data analysis and repo pattern exploration.

## Context

Biologists need a way to select cohorts of GTEx samples (filter by tissue type, quality metrics), then export FASTQ file paths to feed into downstream bioinformatics pipelines (Salmon, FastQC). The existing Workbench Data Explorer is a general-purpose browsing tool that doesn't complete this workflow. A purpose-built Cohort Explorer deployed as a custom Workbench app solves this.

**Branch:** `BENCH-8640-yp-cohort-builder`
**App location:** `src/cohort-explorer/` in `workbench-app-devcontainers`

---

## Corrections to the v2 Plan

| v2 Plan Says | v3 Correction | Why |
|---|---|---|
| 3 ORM tables (Subject + Sample + File) + Cohort | **1 table (Sample).** Cohort deferred to Phase 4 | File is 1:1 with Sample (every row has exactly one fastq pair). Subject has no columns beyond submitter_id -- subject-level counts are `COUNT(DISTINCT subject_id)`, not a join. Over-normalization adds joins for zero benefit. |
| `sample_type` filterable ("RNA / DNA" in UI mockup) | **Drop `sample_type`** | Always "Normal" in all 17,350 rows. Zero filter utility. |
| 7 columns in the model | **20 columns** from the actual 33 | v2 said "may adjust once we confirm the TSV column headers." Now confirmed -- see column disposition below. |
| Cohort save/load in Step 1 | **Phase 4** | Adds 4 endpoints + 2 dialogs + 1 table. Not needed for POC demo. |
| "Token refresh on connection errors" (vague) | **Custom `creator` function** calling `wb resource resolve` per connection | IAM tokens expire after 15min. Needs a concrete solution, not handwaving. |
| Playground app as docker-compose reference | **pgweb app** as reference | Playground uses 3 containers. We need 1. pgweb is the closer pattern. |

---

## Architecture

### Single-container, multi-stage build

```
src/cohort-explorer/
├── .devcontainer.json
├── docker-compose.yaml
├── devcontainer-template.json
├── Dockerfile                    # Stage 1: Node build, Stage 2: Python runtime
├── app/
│   ├── main.py                   # FastAPI + StaticFiles mount
│   ├── db.py                     # Aurora connection via wb resource resolve
│   ├── models.py                 # SQLAlchemy Sample model
│   ├── seed.py                   # TSV -> Aurora bulk insert
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx               # Layout + filter state coordination
│       ├── api.ts                # Fetch helpers (relative paths)
│       ├── types.ts
│       └── components/
│           ├── FilterPanel.tsx   # Cascaded tissue type, checkboxes, range sliders
│           ├── DataGrid.tsx      # AG Grid Community wrapper
│           └── SummaryBar.tsx    # "X subjects, Y samples, Z FASTQ pairs"
└── README.md
```

**Why single container:** FastAPI serves React static files via `StaticFiles` mount. No Caddy/nginx needed. Workbench proxy handles TLS/auth. One container, one process (uvicorn), one port (8080). The pgweb app proves this pattern works in this repo.

**Reference files to follow:**
- `src/pgweb/docker-compose.yaml` -- single-service build pattern
- `src/pgweb/.devcontainer.json` -- devcontainer with database features
- `src/pgweb/devcontainer-template.json` -- standard cloud/login options

---

## TSV Column Disposition (all 33 columns)

### DROP (12 columns)

Single-valued or empty: `type` (always "sample"), `sample_provider`, `sample_source`, `tissue_affected_status`, `sample_type` (always "Normal"), `state` (always "validated"), `project_id` (always "CF-GTEx"), `internal_notes_ldacc`

Administrative: `created_datetime`, `updated_datetime`, `id` (Gen3 UUID), `subjects.id` (Gen3 UUID)

### STORE -- Filterable (8 columns)

| TSV Column | DB Type | Filter Type | Cardinality | Null handling |
|---|---|---|---|---|
| `tissue_type` | `TEXT NOT NULL` | Multi-select checkbox | 30 | No nulls in data |
| `tissue_type_detail` | `TEXT NOT NULL` | Multi-select autocomplete, **cascaded from tissue_type** | 54 | No nulls in data |
| `autolysis_score` | `TEXT` | Multi-select checkbox | 5: None/Mild/Moderate/Severe + **"Unknown"** | 3,580 blanks (20.6%) -> stored as NULL, shown as "Unknown" in filter |
| `current_material_type` | `TEXT` | Multi-select checkbox | 5 (Tissue:PAXgene, Tissue:Fresh Frozen, etc.) | 17 blanks -> NULL |
| `sample_collection_kit` | `TEXT` | Multi-select checkbox | ~3 | 17 blanks -> NULL |
| `rin_number` | `NUMERIC(3,1)` | Range slider (3.2 - 10.0) | Continuous, **rounded at seed time** | 0 nulls |
| `total_ischemic_time` | `FLOAT` | Range slider (includes negative values) | Continuous | 26 blanks -> NULL, excluded from slider range |
| `paxgene_time` | `FLOAT` | Range slider | Continuous | 3,603 blanks (20.8%) -> NULL |

**Changes from initial draft (per critic review):**
- `current_material_type` promoted from display-only to filterable (5 meaningful values: preservation method matters for RNA-seq)
- `bss_collection_site` demoted to display-only (compound values like "C1, A1" make poor filter options)
- `autolysis_score` cardinality corrected from 4 to 5 (includes 3,580 blank rows)
- `rin_number` stored as `NUMERIC(3,1)` not `FLOAT` (avoids IEEE 754 artifacts like `8.399999618530272` in UI)
- `paxgene_time` promoted to filterable (meaningful for sample quality)

### STORE -- Display-only in grid (12 columns)

Identifiers: `subjects.submitter_id` (as `subject_id`), `gtex_sample_id`, `specimen_id`, `dbgap_sample_id`, `submitter_id`, `SRR_id`

Scientific context: `tissue_location`, `bss_collection_site`, `original_material_type`, `pathology_notes_prc`, `prosector_comments`

Export targets: `fastq1_path`, `fastq2_path`

### Cascaded filter behavior

When the user selects "Brain" in `tissue_type`, the `tissue_type_detail` dropdown shows only Brain subtypes (Cortex, Cerebellum, etc.), not all 54 values. The `/api/filters` endpoint accepts current filter state and returns filtered distinct values.

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET /` | Serve React app (index.html from static/) | |
| `GET /api/health` | Returns 200 immediately (before seeding). Workbench proxy health check. | |
| `GET /api/samples` | Filtered samples for AG Grid (accepts filter params as JSON query) | |
| `GET /api/filters` | Distinct values for each filter dimension, **scoped to current filters** | |
| `GET /api/counts` | Subject count, sample count, FASTQ pair count for current filters | |
| `GET /api/export` | CSV download of filtered samples (pipeline-ready manifest format) | |
| `POST /api/seed` | Seed from TSV. Idempotent via `INSERT ... ON CONFLICT (gtex_sample_id) DO NOTHING`. | |

Cohort CRUD endpoints (`POST/GET/DELETE /api/cohorts`) deferred to Phase 4.

---

## Execution Phases

### Phase 0: Skeleton + CI (1 session)

**Goal:** Container builds, starts, serves hello page, CI green.

Files to create:
- `src/cohort-explorer/.devcontainer.json` (following pgweb pattern)
- `src/cohort-explorer/docker-compose.yaml` (single service, build from Dockerfile)
- `src/cohort-explorer/devcontainer-template.json` (cloud/login options)
- `src/cohort-explorer/Dockerfile` (multi-stage: node:20-alpine + python:3.12-slim)
- `src/cohort-explorer/app/main.py` (FastAPI with `GET /` returning placeholder)
- `src/cohort-explorer/app/requirements.txt`
- `src/cohort-explorer/frontend/` (minimal Vite + React scaffold)

CI integration:
- Add `cohort-explorer: {}` to matrix in `.github/workflows/test-pr.yaml`
- Create `tests/cohort-explorer.sh` (verify container starts, curl localhost:8080 returns 200)

**Exit:** `devcontainer up` succeeds, `curl localhost:8080` returns content.

### Phase 1: Data Layer (2 sessions)

**Goal:** TSV seeded into Aurora, API serves filtered data.

Files to create/modify:
- `app/models.py` -- SQLAlchemy `Sample` model with 20 columns, strict typing (Mapped[])
- `app/db.py` -- Aurora connection with IAM token refresh via custom `creator`, pool_recycle=600
- `app/seed.py` -- TSV parser, bulk insert, data quality rules (sentinel conversion, FP rounding)
- `app/main.py` -- Add `/api/health`, `/api/samples`, `/api/filters`, `/api/counts`, `/api/seed`
- `app/requirements.txt` -- Pin: `fastapi>=0.115,<1.0`, `sqlalchemy>=2.0,<3.0`, `psycopg[binary]>=3.1,<4.0`, `uvicorn>=0.32,<1.0`

**Exit:** Seed loads TSV. `GET /api/samples?tissue_type=Brain` returns correct data. `GET /api/filters` returns correct distinct values with "Unknown" for NULL categories. `GET /api/health` returns 200.

### Phase 2: Frontend (2 sessions)

**Goal:** Working filter panel, grid, counts, CSV export.

Files to create/modify:
- `frontend/src/App.tsx` -- Layout, filter state lifted here
- `frontend/src/components/FilterPanel.tsx` -- MUI Autocomplete/Checkbox/Slider
- `frontend/src/components/DataGrid.tsx` -- AG Grid Community
- `frontend/src/components/SummaryBar.tsx` -- Subject/sample/file counts
- `frontend/src/api.ts` -- Typed fetch wrappers
- `frontend/src/types.ts` -- Shared types
- Wire multi-stage Dockerfile to build frontend and serve from FastAPI

**Exit:** User can filter by tissue type, see updated counts, browse in grid, export CSV. **Demonstrable to the partner.**

### Phase 3: Polish (1 session)

**Goal:** Error handling, empty states, responsive layout, README.

- Global FastAPI exception handler returning JSON errors (not HTML 500 pages)
- Structured logging for seed operations, query performance, connection errors
- Empty state UI when filters return 0 results
- Responsive layout for smaller screens
- README with deployment instructions

No new features. Make existing features work well. This phase absorbs Phase 2 bugs.

### Phase 4: Enhancements (post-demo, only if POC approved)

- Cohort save/load (Cohort table + CRUD endpoints + CohortDialog component)
- Workflow integration (Salmon/FastQC submission -- format TBD from the workflow team)
- Verily style guide (MUI theme + AG Grid theme from HTML/CSS guide)
- Schema discovery (`automap_base()` for new datasets)

---

## Why This App Exists (vs Data Explorer)

Data Explorer is a capable, production-grade cohort builder. It exports CSVs and Jupyter notebooks with SQL, persists cohorts with a full artifact hierarchy (Studies > Cohorts > Reviews > Annotations), has configurable bar chart visualizations, and is schema-agnostic via its entity model and protocol buffer configs. It is not a weak tool.

**The primary reason this app exists is that Data Explorer's query engine is BigQuery-only, and this GTEx data lives in Aurora.** Connecting Data Explorer to Aurora would require extending its query engine -- a platform-level engineering effort, not a configuration change.

Given that constraint, building a lightweight custom app is faster than extending Data Explorer. The secondary benefits:

1. **Pipeline-ready export.** Data Explorer exports generic CSVs and notebooks. Cohort Explorer can export FASTQ manifests formatted for Salmon/Nextflow -- the specific downstream workflow for this dataset.

2. **Lighter deployment.** Data Explorer requires a Spring Boot backend, PostgreSQL application database, BigQuery indexer, and protocol buffer configuration. Cohort Explorer is a single container in the workspace, zero infrastructure beyond Aurora.

3. **Faster iteration.** Adding a filter, changing an export format, or tweaking the UI is a code change deployed in hours. Data Explorer changes go through entity model configs, indexer re-runs, and platform release cycles.

4. **Domain-specific UX.** Cascaded tissue_type -> tissue_type_detail filters, range sliders for RIN/ischemic time, subject-level aggregation counts. These are possible in Data Explorer via configuration, but would require writing entity model definitions, prepackaged criteria configs, and visualization protocol buffers for this specific dataset.

---

## What We Knowingly Sacrifice vs Data Explorer

Data Explorer is a mature platform product. This POC deliberately trades breadth for speed-to-demo.

1. **Export model breadth.** Data Explorer has 6 export models (CSV download, CSV to workspace, notebook download, notebook to workspace, notebook preview, regression test JSON). We have 1 (CSV download). Data Explorer can also export notebooks with embedded SQL queries that reproduce the cohort -- we cannot.

2. **Cohort persistence and artifact hierarchy.** Data Explorer persists cohorts in PostgreSQL with a full Studies > Cohorts > Reviews > Annotations hierarchy, activity logging, and underlay version tracking. We have no cohort persistence in the MVP (Phase 4 adds basic save/load).

3. **Visualization.** Data Explorer has configurable bar charts for cohort breakdowns (e.g., samples by gender, age distributions). We show counts and a data grid, no charts.

4. **Boolean logic composition.** Data Explorer supports structured criteria with modifiers. Our filters are AND-only across dimensions.

5. **Schema-agnostic configuration.** Data Explorer onboards new datasets via entity model definitions and protocol buffer configs -- no code changes. Our app is hardcoded to the GTEx schema; new datasets require code changes (until Phase 4 schema discovery).

6. **Multi-dataset studies.** Data Explorer groups cohorts across datasets with access control at study or underlay level. We support one dataset per deployment.

7. **Scale.** Data Explorer uses BigQuery (handles billions of rows). Our client-side AG Grid caps at ~100k rows.

8. **Operational maturity.** Auth, RBAC, audit logging, monitoring, multi-user collaboration -- all built into Data Explorer. None of it exists in this POC.

---

## Data Quality Rules (applied at seed time)

These rules apply in `seed.py` during TSV -> Aurora ingestion:

1. **Sentinel values:** Convert literal `"n/a"` strings to NULL (affects 8,728/17,350 SRR_id values, 50.3% of rows).
2. **Empty strings:** Convert empty/whitespace-only strings to NULL across all TEXT columns.
3. **Floating-point rounding:** Round `rin_number` to 1 decimal place at seed time (e.g., `8.399999618530272` -> `8.4`). Store as `NUMERIC(3,1)`.
4. **Conflict resolution:** `INSERT ... ON CONFLICT (gtex_sample_id) DO NOTHING` for idempotent re-seeding.
5. **Filter display for NULLs:** Filterable columns with NULL values show an "Unknown" option in the filter panel. Selecting "Unknown" returns rows where that column IS NULL.

---

## Seeding Strategy

**Seed via `postCreateCommand`, not on first API request.** The v2 plan proposed auto-seeding on first request; the critic correctly identified a race condition (two concurrent requests both triggering seed). Instead:

- `postCreateCommand` in `.devcontainer.json` calls a seed script after `post-startup.sh`
- The seed script checks if the `samples` table exists and has rows; if not, it loads the TSV
- The `POST /api/seed` endpoint remains available for manual re-seeding but is not auto-triggered
- This is consistent with how other apps in this repo initialize (pgweb's bookmark refresh, playground's DB migrations)

---

## Connection Pool Configuration

```python
engine = create_engine(
    "postgresql://",
    creator=lambda: get_fresh_connection(),  # calls wb resource resolve each time
    pool_pre_ping=True,        # detect stale connections
    pool_recycle=600,          # rotate connections every 10min (under 15min IAM expiry)
    pool_size=5,               # single-user app, small pool
)
```

---

## Open Risks Requiring Owner Decision

1. **Aurora resource ID and creation** -- Who creates the Aurora instance in `gtex-demo-project`? What is the resource ID?
2. **S3 mount path** -- Where does gcsfuse mount the TSV inside the container? Needs to be an env var.
3. **Export format** -- What downstream tool consumes the export? CSV sample manifest with (sample_id, fastq1, fastq2) columns? Or Nextflow params.json? **Must be confirmed with the workflow team before Phase 2.**
4. **Negative ischemic times** -- The data has values down to -1287 minutes. The range slider must handle this. Worth a label/tooltip explaining what negative values mean.
5. **FASTQ path prefix** -- All paths start with `s3://gcs-external-data-prd/`. Should the export rewrite these to workspace-relative paths? Note: paths use two directory structures (`delivered_as_fq/` vs `converted_from_bam/`) indicating different provenance.
6. **Cohort save/load in demo** -- Is "filter -> export" sufficient for the the partner demo, or does the partner expect "filter -> save cohort -> reload later -> export"? If the latter, cohort persistence moves from Phase 4 to Phase 2.

---

## Verification Plan

1. **Phase 0:** `devcontainer up --workspace-folder ./src/cohort-explorer` succeeds. `curl localhost:8080` returns 200. CI smoke test passes.
2. **Phase 1:** Seed via `/api/seed`, then verify:
   - `GET /api/samples?tissue_type=Brain` returns ~2,600 rows
   - `GET /api/filters` returns 30 tissue types, 54 tissue type details
   - `GET /api/counts` with no filters returns 948 subjects, 17,350 samples
3. **Phase 2:** Open in browser. Select "Brain" in tissue type filter. Verify tissue_type_detail cascades to show only brain subtypes. Verify counts update. Adjust RIN slider. Export CSV and verify it contains fastq paths. Test with all filters cleared (full dataset). Test with filters that return 0 results (empty state).
4. **End-to-end:** Deploy to `gtex-demo-project` workspace. Seed from actual S3-mounted TSV. Filter, export, verify FASTQ paths resolve to real S3 objects.

---

## Appendix: Critic Review Summary (Opus agent)

An independent Opus agent reviewed this plan with the AGENTS.md Principal Python Engineer persona. Key findings incorporated above:

**Incorporated fixes:**
1. Null/empty/sentinel handling strategy added (Section: Data Quality Rules)
2. `autolysis_score` cardinality corrected from 4 to 5 (3,580 blank rows)
3. `rin_number` type changed from FLOAT to NUMERIC(3,1) to avoid IEEE 754 artifacts
4. Seeding moved from auto-on-first-request to `postCreateCommand` (eliminates race condition)
5. `/api/health` endpoint added
6. `pool_recycle=600` and `pool_pre_ping=True` specified for SQLAlchemy engine
7. `current_material_type` promoted to filterable (preservation method matters for RNA-seq)
8. `bss_collection_site` demoted from filterable (compound values make poor filter UX)
9. SRR_id `"n/a"` sentinel issue documented (8,728 rows, 50.3%)
10. Dependency pinning specified in requirements.txt
11. Operational maturity gap added to "what we sacrifice" section
12. Export format confirmation elevated to "must resolve before Phase 2"
13. Cohort save/load added as open question for demo scope

**Critic's residual concerns (not blocking, noted for awareness):**
- Multi-stage Dockerfile is a new pattern in this repo (no precedent to copy from)
- Session estimates may be optimistic: critic estimates 7-8 sessions total vs plan's 5-6
- CORS configuration for Vite dev server not explicitly mentioned (Vite proxy should handle it, but worth a note)
- No FastAPI `TestClient` unit tests in scope (acceptable for POC, but noted)
- Future subject-level metadata (age, sex, death classification) may exist in companion TSVs -- if so, a Subject table becomes justified (Phase 4 consideration)

**Critic's overall verdict:** "70% ready" before fixes, "ready for implementation" after the above incorporations.
