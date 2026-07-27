# Cohort Explorer

No-code cohort exploration app for tabular sample data. Point it at any Aurora table/view or a CSV/TSV in S3, and it infers a schema, then lets you browse and filter rows, visualize distributions, save cohorts, export TSV manifests, and submit workflow jobs — all from a browser.

Originally built for GTEx V8 sample data, now datasource- and workflow-agnostic.

## Using the App

### Connecting to data

On launch, the app shows a datasource selector with two kinds of source:

- **Aurora database** — pick a resource, then pick a table or view. Table lists are pre-warmed at startup so the dropdown is populated when the selector appears.
- **Load from file (S3)** — pick an S3 folder, then a `.csv` / `.tsv` / `.txt` file. The file is downloaded and loaded into a local table.

After you pick a source, the app **infers a schema** (column types + which columns are filterable) and shows a **Schema Review** step where you can adjust column types, filter kinds, and display labels before confirming. Your selection and filters are remembered across page refreshes.

### Schema inference

Column types are inferred from the data, not just the declared database type:

- CSV/TSV: samples up to 5000 rows; a column is treated as numeric if ≥90% of non-empty values parse as numbers (tolerates a little noise).
- Aurora: reads `information_schema`, and also inspects `text` columns — if every non-empty value is numeric, it reclassifies as integer/float.
- Filter kind is derived from type and cardinality: low-cardinality → categorical (checkboxes), numeric high-cardinality → range slider, high-cardinality text → not filterable.

You can override any of these in the Schema Review step.

### Filtering

The left panel renders one control per filterable column from the confirmed schema — categorical columns get searchable checkbox lists, numeric columns get range sliders. Select filters, click **Apply Filters** to update the grid and charts, **Reset** to clear.

### Charts

The chart dashboard supports bar, pie, histogram, box plot, scatter, heatmap, and KDE. Click **+** to add a chart on any field. Charts are interactive — clicking a bar or slice applies that value as a filter.

### Cohorts

**Save** the current filter set as a named cohort (persisted to S3 under the cohort storage folder). Cohorts are scoped to their datasource, so you only see cohorts relevant to the active dataset. Load a saved cohort to re-apply its filters.

### Exporting data

Click **Export TSV** to download the currently filtered rows as a tab-separated file.

### Running workflows

Click **Run Workflow** to open the workflow runner:

1. Pick any registered workspace workflow (fetched live from the workspace).
2. The dialog shows the workflow's WDL inputs in a table (Input Key / Type / Values), mirroring the Workbench job-submission UI. Toggle "Required" vs "All" to filter the list.
3. For each input, bind it to a **cohort column** or enter a **static value**. Inputs whose name matches a cohort column are auto-bound. Complex types (Array/Map/etc.) take a JSON-string static value, validated inline.
4. A live preview shows the batch rows that will be submitted.
5. Submit builds a batch CSV and column-mapping file, uploads both to the input bucket, and submits the workflow. Each row becomes one workflow run.

> The app does not verify that your cohort data is semantically valid for the chosen workflow (for example, that a File input points to a resolved `s3://` URI). A banner reminds you to check the workflow's own input requirements before submitting.

## Developer Guide

### Architecture

Single-container app: FastAPI backend + React frontend compiled to static files at build time.

```
src/cohort-explorer/
├── Dockerfile                  # Multi-stage: node build + python runtime
├── docker-compose.yaml         # Container config, ports, FUSE caps
├── devcontainer-template.json  # Workbench app template (cloud, login options)
├── pytest.ini                  # Test config (registers "slow" marker)
├── scripts/
│   ├── pre-commit.sh           # Hook: tsc --noEmit + backend import check
│   └── install-hooks.sh        # Installs the pre-commit hook
├── app/
│   ├── main.py                 # FastAPI endpoints
│   ├── db.py                   # Aurora/SQLite connections + resource/table caching
│   ├── dynamic_model.py        # Builds a SQLAlchemy model at runtime from the confirmed schema
│   ├── schema.py               # Schema inference (CSV + Aurora), mapping CSV I/O
│   ├── models.py               # Static Sample model (fallback / legacy GTEx samples view)
│   ├── seed.py                 # TSV/CSV loader for SQLite
│   ├── cohorts.py              # Cohort save/load with S3 persistence
│   └── tests/                  # pytest unit tests (see Testing)
└── frontend/
    ├── src/
    │   ├── App.tsx                    # Root component, state, render flow
    │   ├── api.ts                     # Backend API client + types
    │   ├── types.ts                   # Filter state, chart config, field meta
    │   └── components/
    │       ├── ResourceSelector.tsx   # Datasource picker (Aurora table or S3 file)
    │       ├── SchemaReview.tsx       # Editable inferred-schema table
    │       ├── FilterPanel.tsx        # Dynamic filter sidebar
    │       ├── DataGrid.tsx           # AG Grid table
    │       ├── SummaryBar.tsx         # Counts + save/export/workflow buttons
    │       ├── RunWorkflowDialog.tsx  # Generic workflow runner
    │       ├── SaveCohortDialog.tsx   # Cohort save dialog
    │       ├── ConnectionError.tsx    # Error banner with retry
    │       └── charts/                # Chart dashboard components
    └── vite.config.ts                 # sourcemap enabled for prod DevTools
```

### Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, psycopg3, uvicorn
- **Frontend:** React 19, MUI 9, AG Grid Community, Recharts, Allotment, Vite
- **Database:** Aurora PostgreSQL (via `wb resource resolve`) or SQLite (file loading + local dev)
- **Container base:** `mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm`

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/datasources` | Aurora resources (with pre-warmed tables) + S3 folders + `ready` flag |
| `POST` | `/api/datasources/refresh` | Force-refresh resource list |
| `GET` | `/api/s3/files` | List CSV/TSV/TXT files in an S3 folder (cached) |
| `POST` | `/api/schema/infer` | Infer schema from a file or Aurora table |
| `POST` | `/api/schema/confirm` | Save the confirmed schema; build dynamic model; seed if file |
| `GET` | `/api/schema/active` | Current active schema mapping |
| `POST` | `/api/connect` | Set active datasource |
| `GET` | `/api/samples` | Query rows with filters (LIMIT-capped) |
| `GET` | `/api/filters` | Distinct values + counts / ranges for filter controls |
| `GET` | `/api/counts` | Summary counts |
| `GET` | `/api/export` | Download filtered results as TSV |
| `POST` | `/api/seed` | Seed SQLite from TSV (local dev) |
| `GET`/`POST`/`DELETE` | `/api/cohorts*` | Cohort list/get/save/delete/exists (S3-backed, datasource-scoped) |
| `GET` | `/api/workflows` | List registered workflows + S3 folders |
| `GET` | `/api/workflows/{name}/inputs` | WDL inputs for a workflow |
| `POST` | `/api/workflows/{name}/prepare` | Build batch preview from column bindings |
| `POST` | `/api/workflows/{name}/submit` | Build CSV + mapping, upload, submit job (async) |
| `GET` | `/api/workflows/jobs/{job_id}` | Poll workflow submission status |

### Dynamic schema

`schema.py` infers a list of `ColumnMapping{column, type, filter, label}`. `dynamic_model.py` builds a SQLAlchemy model at runtime with Python's `type()` from the confirmed mappings, and persists the active mapping to `app/active_schema.json` so it survives a uvicorn restart. All query endpoints operate on this dynamic model via `get_active_model()`, falling back to the static `Sample` model (`models.py`) when no schema is active.

### Caching & startup

The `wb` CLI is slow inside app containers (calls go through the Workbench backend; several seconds to a minute each), and the Workbench proxy times out at ~60s. The backend pre-warms and caches aggressively:

- **Workspace** — all `wb`-dependent startup work is deferred until the workspace context is set: a background gate polls the `wb` context file directly (no `wb` subprocess) until a workspace is present, then warms resources. `GET /api/ready` reports readiness, and the UI holds a "Connecting to workspace…" spinner until then.
- **AWS profiles** — `wb workspace configure-aws` runs at startup and `AWS_CONFIG_FILE` is auto-discovered; all `aws s3` calls use `--profile <resource_id>`.
- **Resource list + Aurora tables** — fetched in a background thread at startup; the datasources endpoint blocks until ready and returns tables inline.
- **S3 file listings** — pre-warmed per folder at startup, cached, background-refreshed on subsequent calls.
- **Connection strings** — cached after first resolve; expired tokens detected on failure and re-resolved.

All `wb` subprocess calls use a 120-second timeout.

### Testing

Backend unit tests use pytest (`app/tests/`). They avoid `wb`, S3, Aurora, and threads — pure logic against in-memory data.

```bash
cd src/cohort-explorer
pip install -r app/requirements-dev.txt
python3 -m pytest
```

A **pre-commit hook** runs `tsc --noEmit` (if frontend files are staged) and `python3 -c "from main import app"` (if backend files are staged). It's scoped to `src/cohort-explorer/` and no-ops for commits elsewhere. Install it once:

```bash
bash src/cohort-explorer/scripts/install-hooks.sh   # bypass a commit with --no-verify
```

### Local development

Runs locally with SQLite (no Aurora needed). Aurora and workflow calls require an authenticated `wb` workspace context; Aurora additionally needs VPC network access (won't work from a laptop, works from a cloud workstation in-region).

```bash
wb workspace set <workspace-id>

# Backend
cd app
pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to the FastAPI backend, and gives you frontend hot-reload (no Docker rebuild needed for UI iteration).

### Hot-patching the deployed app

**Backend only** (Python files are interpreted at runtime):
```bash
sudo docker exec application-server bash -c '\
  curl -fSL "https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/BENCH-8640-cohort-explorer/src/cohort-explorer/app/<file>.py" \
  -o /app/<file>.py && pkill -f uvicorn'
```

**Frontend changes require a full rebuild** — the React app is compiled to static JS at Docker build time. Curling `.tsx` source into the container does not update the compiled bundle. Creating a new custom app is the reliable way to deploy frontend changes.

### Deploying

Register the app config in a Workbench workspace:

```bash
wb app config create \
  --name="Cohort Explorer" \
  --git-repo-url="https://github.com/verily-src/workbench-app-devcontainers.git" \
  --git-branch="BENCH-8640-cohort-explorer" \
  --dev-container-path="src/cohort-explorer" \
  --description="No-code cohort exploration with workflow submission"
```

Then create the app from the Workbench UI.

### Region constraint

All resources should be in the same AWS region as the Aurora DB and the app VM. Cross-region Aurora connections hang. If the app VM is in the wrong region, delete and recreate it — stop/start preserves the same VM.
