# WB Data Catalog

React + FastAPI app: browse all BigQuery datasets/tables in a GCP project, preview capped rows, run **technical (C2a)** and **semantic (C2b)** profiling on demand, view profiles from GCS, and get **LLM-suggested charts** (Gemini).

UI uses lightweight **Verily Pre–inspired** tokens and RDS-shaped primitives in `frontend/src/components/rds.tsx` — swap in `@verily-src/rds-*` when your npm registry is configured.

## Environment variables

| Variable | Description |
|----------|-------------|
| `GCP_PROJECT_ID` | Billing / ADC project for BigQuery jobs and Vertex AI |
| `DATA_PROJECT_ID` | Project whose datasets are listed (defaults to `GCP_PROJECT_ID`) |
| `PROFILE_GCS_BUCKET` | Bucket name (no `gs://`) where `profiling/{project}/{dataset}/{table}/tech_profile.json` and `semantic_profile.json` are stored |
| `GEMINI_MODEL` | Optional override (e.g. `gemini-2.5-flash`) |
| `FRONTEND_DIST` | Optional path to built SPA (default: `backend/static` in Docker image) |

## Local development

### One-time setup

Create the backend venv and install dependencies (from the catalog root):

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../packages/verily-profiler
pip install -e "../packages/verily-chat[agent]"
```

Install frontend dependencies:

```bash
cd frontend
npm install
```

### Running the app

Start **both** servers — the Vite dev server proxies `/api` calls to the backend automatically.

**Terminal 1 — Backend** (from `backend/`):

```bash
cd backend
source .venv/bin/activate
export GCP_PROJECT_ID=your-billing-project
export DATA_PROJECT_ID=your-data-project   # optional, defaults to GCP_PROJECT_ID
uvicorn main:app --host 127.0.0.1 --port 8080
```

**Terminal 2 — Frontend** (from `frontend/`):

```bash
cd frontend
npm run dev
```

Open http://localhost:5173/ in your browser. The frontend runs on port 5173 and proxies all `/api/*` requests to the backend on port 8080.

### Production-style single-process serving

Build the SPA into `backend/static` so uvicorn serves everything:

```bash
cd frontend && npm run build && mkdir -p ../backend/static && rm -rf ../backend/static/* && cp -r dist/* ../backend/static/
cd ../backend && source .venv/bin/activate && FRONTEND_DIST=./static uvicorn main:app --host 0.0.0.0 --port 8080
```

## Docker / Compute Engine

**Workbench / local compose:** `docker-compose.yaml` follows [workbench-app-devcontainers](https://github.com/vrajat44/workbench-app-devcontainers/blob/master/README.md) (same pattern as `src/example/docker-compose.yaml`): `container_name: application-server`, external **`app-network`**, and FUSE flags for gcsfuse. Before `docker compose up` locally, create the network once:

```bash
docker network create app-network
```

Then:

```bash
docker compose build
export GCP_PROJECT_ID=...
export DATA_PROJECT_ID=...   # optional; defaults to billing project
docker compose up
```

Workbench creates `app-network` in its environment; you do not manage that in the cloud UI.

On **Compute Engine**, use a service account with:

- BigQuery: `bigquery.jobs.create`, read metadata and table data for preview/profiling
- Storage: read/write objects on `PROFILE_GCS_BUCKET`
- Vertex AI: Gemini access in your region

Reserve a static external IP, allow TCP **8080** in firewall rules, then open `http://<EXTERNAL_IP>:8080`.

## API summary

- `GET /api/catalog` — all datasets + tables + profiling flags from GCS index
- `GET /api/projects/{p}/datasets/{d}/tables/{t}/preview` — capped preview
- `POST .../profile/technical` / `POST .../profile/semantic` — start profiling (async)
- `GET .../profile/status` — `{ technical, semantic }` states
- `GET .../profile/technical` / `.../semantic` — JSON profiles
- `POST /api/charts/suggest` — body `{ technical, semantic? }` → suggested charts

## Repo layout

- `backend/` — FastAPI, BQ preview/discovery, profiling runner, chart advisor, vendored `profiler/` package from WB Data Profiler
- `frontend/` — Vite + React + Recharts
- `Dockerfile` / `docker-compose.yaml` — production-style container
