# Cohort Explorer

No-code cohort exploration app for GTEx V8 sample data. Browse and filter 22,953 samples across tissue types, visualize distributions, export TSV manifests, and submit Salmon RNA-seq workflows — all from a browser.

## Using the App

### Connecting to data

On launch, the app shows a datasource selector. Pick an Aurora database from the workspace or use the local SQLite fallback for demo purposes. The app remembers your selection across page refreshes.

If Aurora resources don't appear immediately, wait a few seconds and click the refresh button — the resource list is fetched in the background on startup.

### Filtering samples

The left panel has 8 filter dimensions:

| Filter | Type | Notes |
|--------|------|-------|
| Tissue Type | Categorical (searchable) | 31 tissue types |
| Tissue Detail | Categorical (searchable) | 54 sub-types |
| Autolysis Score | Categorical | 4 values |
| Material Type | Categorical | |
| Collection Kit | Categorical | |
| RIN Number | Range slider | RNA Integrity Number |
| Ischemic Time | Range slider | Minutes |
| PAXgene Time | Range slider | Minutes |

Tissue Type and Tissue Detail have a search box to quickly find options. Select filters, then click **Apply Filters** to update the grid and charts. Click **Reset** to clear all filters.

### Charts

The chart dashboard above the data grid supports multiple chart types (bar, pie, histogram, box plot, scatter, heatmap, KDE). Click the **+** button to add charts on any field. Charts are interactive — clicking a bar or slice applies that value as a filter.

### Exporting data

Click **Export TSV** to download the currently filtered samples as a tab-separated file.

### Running Salmon workflows

Click **Run Salmon** to submit a Salmon v1.10.1 RNA-seq quantification workflow for the filtered samples that have FASTQ paths. The workflow runs asynchronously via AWS HealthOmics. Only samples with `fastq1_path` populated are included.

## Developer Guide

### Architecture

Single-container app: FastAPI backend + React frontend compiled to static files at build time.

```
src/cohort-explorer/
├── Dockerfile                  # Multi-stage: node build + python runtime
├── docker-compose.yaml         # Container config, ports, FUSE caps
├── devcontainer-template.json  # Workbench app template (cloud, login options)
├── app/
│   ├── main.py                 # FastAPI endpoints
│   ├── db.py                   # Aurora/SQLite connection management + caching
│   ├── models.py               # SQLAlchemy model (maps to `samples` view)
│   └── seed.py                 # TSV loader for SQLite local dev
└── frontend/
    ├── src/
    │   ├── App.tsx             # Root component, state management
    │   ├── api.ts              # Backend API functions
    │   ├── types.ts            # TypeScript types + filter state
    │   └── components/
    │       ├── FilterPanel.tsx      # Filter sidebar with search
    │       ├── DataGrid.tsx         # AG Grid table
    │       ├── SummaryBar.tsx       # Counts + export/workflow buttons
    │       ├── ResourceSelector.tsx # Datasource picker on launch
    │       ├── RunSalmonDialog.tsx  # Workflow confirmation dialog
    │       └── charts/             # Chart dashboard components
    └── vite.config.ts
```

### Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy, psycopg3, uvicorn
- **Frontend:** React 19, MUI 9, AG Grid Community, Recharts, Allotment, Vite
- **Database:** Aurora PostgreSQL (via `wb resource resolve`) or SQLite (local fallback)
- **Container base:** `mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm`

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/datasources` | List Aurora resources (cached) |
| `POST` | `/api/datasources/refresh` | Force-refresh resource list |
| `POST` | `/api/connect` | Set active datasource |
| `GET` | `/api/samples` | Query samples with filters |
| `GET` | `/api/filters` | Distinct values + counts for filter dropdowns |
| `GET` | `/api/counts` | Summary counts (samples, subjects, FASTQ pairs) |
| `GET` | `/api/export` | Download filtered results as TSV |
| `POST` | `/api/seed` | Seed SQLite from TSV (local dev only) |
| `POST` | `/api/salmon/prepare` | Preview Salmon batch for current filters |
| `POST` | `/api/salmon/submit` | Submit Salmon workflow (async) |
| `GET` | `/api/salmon/status/{id}` | Poll workflow job status |

### Data model

The app queries a `samples` view in Aurora that maps raw GTEx column names to readable names. The view sits on top of the `gtex_sample_attributes` table (22,953 rows, 63 columns). See `models.py` for the SQLAlchemy mapping.

### Caching

The `wb` CLI is slow inside app containers (30-120 seconds per call). The backend caches:

- **Resource list** (`wb resource list`): fetched synchronously on first call, then background-refreshed on subsequent calls. Module-level cache in `db.py`.
- **Connection strings** (`wb resource resolve`): cached after first resolution. Expired tokens are detected on connection failure and refreshed automatically.

All `wb` subprocess calls use a 120-second timeout.

### Local development

The app can run locally with SQLite (no Aurora needed):

```bash
# Backend
cd app
pip install -r requirements.txt
TSV_PATH=/path/to/GTEx_V8_sample_manifest_metadata.tsv uvicorn main:app --reload --port 8080

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the FastAPI backend.

### Hot-patching the deployed app

**Backend only** (Python files are interpreted at runtime):
```bash
sudo docker exec application-server bash -c '\
  curl -fSL "https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/BENCH-8640-cohort-explorer/src/cohort-explorer/app/<file>.py" \
  -o /app/<file>.py && pkill -f uvicorn'
```

**Frontend changes require a full rebuild** — the React app is compiled to static JS at Docker build time. Curling `.tsx` source files into the container does not update the compiled bundle.

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

Then create the app from the Workbench UI. **The workspace default region must match the Aurora DB region (us-west-2).**

### Region constraint

All resources must be in the same AWS region (us-west-2): Aurora DB, S3 buckets, ECR images, HealthOmics, and the app VM. Cross-region connections will hang or error. If the app VM is in the wrong region, delete and recreate it — stop/start preserves the same VM.
