# Cohort Studio

Next-generation cohort exploration app: a **React + TypeScript** frontend
with Linear-inspired design over a **FastAPI** backend that reuses the
proven engine modules from [Cohort Dashboard](../cohort-dashboard/)
(Aurora via SQLAlchemy, S3 Parquet/CSV via DuckDB, BigQuery, lineage,
TTL caching).

## Architecture

```
Browser (React/TS, ECharts)  ── REST ──  FastAPI (app/main.py)
   thin: renders aggregates              datasets.py: in-memory store +
   sends filters + chart list            server-side cross-filtering
                                         engines: db.py duck.py bq.py
```

The frontend is deliberately thin: one `POST /api/datasets/{id}/query`
round trip returns counts, per-chart aggregates (full cohort + filtered
cohort for the cBioPortal-style overlay), and a page of rows. All pandas
work stays server-side, so the browser never sees more than ~50 rows and
a few hundred aggregate points.

**Why not a Rust backend:** the backend is I/O orchestration — `wb` CLI
subprocesses, Postgres, S3, BigQuery. Rust's strengths don't bind here,
and Python keeps the battle-tested engine modules and first-party cloud
SDKs. The REST contract is the stable boundary: a hot data path could be
reimplemented behind it later without touching the UI.

## Development

```bash
# Backend (terminal 1)
cd src/cohort-studio
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt
cd app && ../.venv/bin/uvicorn main:app --reload --port 8080

# Frontend with hot reload (terminal 2) — proxies /api to :8080
cd src/cohort-studio/web
npm install && npm run dev
```

No workspace needed locally — upload a CSV from the sidebar.

### Testing

```bash
cd src/cohort-studio
.venv/bin/pip install pytest httpx pytest-playwright
.venv/bin/playwright install chromium
cd web && npm run build && cp -r dist ../app/static && cd ..
.venv/bin/python -m pytest            # API + engines + Playwright E2E
.venv/bin/python -m pytest -m "not e2e"  # fast tests only
```

## Deploying

```bash
wb app config create \
  --name="Cohort Studio" \
  --git-repo-url="https://github.com/verily-src/workbench-app-devcontainers.git" \
  --git-branch="cohort-dashboard" \
  --dev-container-path="src/cohort-studio" \
  --description="Cohort exploration studio (React + FastAPI)"
```

Then create the app from the Workbench UI. Known platform issue: first
boots of custom apps frequently hang in post-startup — if the proxy URL
403s after ~15 minutes, stop/start the VM once.

### Shipping updates (restart-to-deploy)

App code is baked into the image at VM creation, but this app
self-updates: `self_update.sh` (in the image) fetches the branch tarball
from GitHub, swaps the backend, rebuilds the frontend in-container, and
restarts the server — no-op when the branch hasn't moved.

- **Restart the VM** → `postStartCommand` runs the script → latest
  branch is live in ~1 minute.
- **No restart at all**: `POST <app-url>/api/admin/update`, then poll
  `GET /api/version` until the sha changes. Progress lands in
  `/tmp/self-update.log` inside the container.

VM recreation is only needed when `.devcontainer.json`, the Dockerfile,
or the compose file change.

The operational notes in [../cohort-dashboard/README.md](../cohort-dashboard/README.md)
(datasource support matrix, aurora_analytics requirements, VM debugging)
apply unchanged.
