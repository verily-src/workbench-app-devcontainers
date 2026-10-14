# Cohort Studio

Next-generation cohort exploration app: a **React + TypeScript** frontend
with Linear-inspired design over a **FastAPI** backend (Aurora via
SQLAlchemy, S3 Parquet/CSV via DuckDB, BigQuery, lineage, TTL caching).

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

## AI providers & agent telemetry

Ask AI (natural-language filtering) and the chat assistant run on a
configurable provider, chosen in **Settings → AI model**:

- **Anthropic (Claude)** — default, via the native SDK (tool runner for
  chat, `messages.parse` structured output for Ask AI).
- **OpenAI** and **Google Gemini** — share one OpenAI-compatible code
  path (`app/providers.py`); Gemini uses its OpenAI-compatible endpoint
  (a `base_url` switch). Model IDs are free text — enter the provider's
  current model, since those IDs change often.

Each provider keeps its own API key and model independently; keys live
server-side and are never echoed back. Env vars take precedence over the
stored key: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
(or `GOOGLE_API_KEY`).

Every chat turn is persisted to the `_agent_turn` table (Aurora when
connected, SQLite fallback otherwise) with OpenTelemetry-shaped fields —
trace id, provider, model, latency, token usage, tool calls, status — so
agent history stays inside the workspace governance boundary and is
exportable to an OTel collector later. View it under **Lineage → Agent
activity**. See `docs/architecture.md` for diagrams.

## Workflow awareness

The **Workflows** tab lists Workbench workflow jobs (`wb workflow job
list`) — Nextflow / HealthOmics runs — with a running-count badge in the
nav. Because each job writes outputs to an S3 bucket resource
(`outputBucketUuid` / `outputBucketPath`), the Explore tab shows a banner
when the loaded datasource shares the output bucket of a job that is
still running, so you know the data may be incomplete. The `wb workflow`
command is optional: if the container's build or workspace can't reach
it, the tab degrades to an "unavailable" state and never errors.

## Views-only DuckDB catalogs

A DuckDB file can hold only `VIEW` definitions that point at data
elsewhere (see the DuckDB post "A DuckDB Database with No Data in It").
The file stays a few hundred KB at any data size and works as a shared,
curated catalog: one URL, many tables.

- **Consume.** Any `*.duckdb` file in a workspace S3 folder shows up as a
  datasource of kind `catalog`, id `<resource_id>/<path>.duckdb` (for
  example `my_folder/_catalog/rail.duckdb`). Extra https catalogs:
  `STUDIO_CATALOG_URLS` (comma-separated `https://` URLs; only listed
  URLs can be attached). The app creates the S3 secret from the folder's
  profile, then `ATTACH '<uri>' AS cat (READ_ONLY)`. The table list shows
  the catalog's views (hover a view to see its SQL). Opening a view runs
  `SELECT * FROM cat.<view> LIMIT <row cap>`, so each load reads current
  data.
- **Build and host.** Select an S3 folder, enter a name, and click
  **Publish catalog** (`POST /api/catalogs/build`). The app writes a local
  catalog with one view per data file. A hive-partitioned set
  (`dir/year=*/…`) becomes one `read_parquet('…/dir/*=*/*.parquet',
  hive_partitioning = true)` view. Every view uses a fully qualified
  `s3://` location. The app checks that the file holds no tables, then
  uploads it to `<folder>/_catalog/<name>.duckdb` with the folder's
  profile. The API also accepts custom views (`views: [{name, sql}]`,
  one `SELECT` each).
- **Update.** You cannot change a catalog in place, because S3 and https
  attachments are read-only. To update it, publish again with the same
  name. You can also edit a local copy (`CREATE OR REPLACE VIEW …`, for
  example to point at a new layout or to rename a column back) and
  upload the copy.
- **Limitations.** Readers need access to the catalog file *and* to
  every source its views reference. A view over a bucket that the
  folder's profile can't read fails, and the error names that source.
  Speed depends on the network and on the file layout.

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

## Datasources

| Datasource | Engine | Workbench resource type |
|---|---|---|
| Aurora tables & views | SQLAlchemy + psycopg | `AWS_AURORA_DATABASE` |
| Parquet/CSV in S3 | **DuckDB** reading S3 directly via the per-resource AWS profiles | `AWS_S3_STORAGE_FOLDER` |
| BigQuery tables (GCP workspaces) | google-cloud-bigquery | `BQ_DATASET` |
| S3 Parquet/Iceberg as Aurora foreign tables | [`aurora_analytics`](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-analytics-tutorial.html) (needs Aurora PostgreSQL 17.11+) | `AWS_AURORA_DATABASE` |
| Local CSV/TSV upload | pandas (dev mode, no workspace needed) | — |

Redshift, Athena, and DynamoDB were evaluated and are not reachable inside
the Workbench credential model (not resource types, so no ABAC credential
path). DuckDB-over-S3 covers the Athena use case within governance.

### Requirements for aurora_analytics

`aurora_analytics` needs cluster-level provisioning that Workbench controls:

- Aurora PostgreSQL **17.11+** (the aurora-resource-demo cluster is 16.9)
- cluster parameter `aurora_analytics.enabled = true`
- an IAM role attached to the cluster with `--feature-name AuroraAnalytics`
  and S3 read access
- an S3 gateway VPC endpoint if the cluster is in a private subnet

Native tables and views work on any cluster version. Aurora access also
requires an authenticated `wb` workspace context and VPC network access
(cloud workstation in-region; not from a laptop).

The VM-debugging rules in [../cohort-explorer/CLAUDE.md](../cohort-explorer/CLAUDE.md)
apply to this app unchanged.
