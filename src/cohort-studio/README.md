# Cohort Studio

Shared agent project state and current work status: [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md).

Next-generation cohort exploration app: a **React + TypeScript** frontend
with Linear-inspired design over a **FastAPI** backend (Aurora via
SQLAlchemy, S3 Parquet/CSV via DuckDB, BigQuery, lineage, TTL caching).

## Architecture

See [the maintained architecture and flow diagrams](docs/architecture.md) for
providers, data access, updates, OMOP, and the isolated-browser deployment.

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
subprocesses, Aurora, S3, BigQuery. Rust's strengths don't bind here,
and Python keeps the battle-tested engine modules and first-party cloud
SDKs. The REST contract is the stable boundary: a hot data path could be
reimplemented behind it later without touching the UI.

## AI providers & agent telemetry

Ask AI (natural-language filtering) and the chat assistant run on a
configurable provider, chosen in **Settings → AI model**:

- **Anthropic (Claude)** — default, via the native SDK (tool runner for
  chat, `messages.parse` structured output for Ask AI).
- **OpenAI**, **Google Gemini**, and **OpenRouter** — share one
  OpenAI-compatible code path (`app/providers.py`). Gemini and OpenRouter
  use their documented endpoints; enter the current model ID in Settings.
- **Amazon Bedrock** — uses the Converse API and the AWS SDK credential
  chain (IAM role, profile, or environment). It needs `AWS_REGION` or
  `AWS_DEFAULT_REGION` and a model ID in Settings. It does not use an API
  key. Choose a Bedrock model that supports Converse tool use.

Each API-key provider keeps its own key and model; keys live server-side
and are never echoed back. Environment keys take precedence over stored
keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` (or
`GOOGLE_API_KEY`), and `OPENROUTER_API_KEY`. Bedrock uses the server's AWS
IAM credentials and region.

Every chat turn is persisted to the `_agent_turn` table (Aurora when
connected, SQLite fallback otherwise) with OpenTelemetry-shaped fields —
trace id, provider, model, latency, token usage, tool calls, status — so
agent history stays inside the workspace governance boundary and is
exportable to an OTel collector later. View it under **Lineage → Agent
activity**. See `docs/architecture.md` for diagrams.

## Agents

Studio has two built-in agents and one entry point for outside agents.
All three work through the same engine layer as the UI (`datasets.py`,
the datasource engines, `llm.validate_filters`), so an agent can only
reach data that the UI can reach.

| Agent | Code | Endpoint | Can change the UI |
|---|---|---|---|
| Ask AI (filter translator) | `app/llm.py` | `POST /api/datasets/{id}/ask` | Yes: returns a filter set |
| Chat assistant | `app/agent.py`, `app/providers.py` | `POST /api/datasets/{id}/chat` | Yes: filters and charts |
| MCP server (outside agents) | `app/mcp_server.py` | `/mcp` (streamable HTTP) | No: read and query only |

**Ask AI** makes one model call with structured output. Bedrock requests
that structure through a Converse tool schema, so its model must support
tool use. It turns a question such as "liver samples with RIN above 7"
into the complete new filter set, using the dataset's column profile and
the current filters. Refinements add to the filters, "instead" replaces
them, and "clear" removes them. The result is checked against the column
profile before it reaches the UI: unknown columns and values are dropped,
and ranges are clamped to the column's bounds. Each call is recorded in
lineage as `ask_ai`.

**Chat assistant** is a tool-using agent for the open dataset. Its system
prompt holds the dataset name, the column profile and the current
filters and charts. It is told to ground every number in a tool result
and to build what the user asks to see rather than describe it. Tools:

- `run_query`: count the rows that match a filter set and preview five.
- `aggregate`: count, mean, median, min, max, sum or nunique, optionally
  grouped (top 25 groups) and filtered.
- `set_filters`: replace the UI filters. The grid, counts and charts
  update.
- `add_chart` / `remove_chart`: bar, histogram, scatter or heatmap cards.

Anthropic runs on the SDK's tool runner. OpenAI, Gemini, and OpenRouter
use one OpenAI-compatible loop; Bedrock uses the Converse tool loop.
Requests are stateless: the browser sends the last 30 messages, and the
endpoint returns the final filters, charts, a list of the actions taken,
and token usage. Every turn is saved to `_agent_turn` with a trace id and
is listed under **Lineage → Agent activity** (`GET /api/agent/turns`).

**MCP server** lets outside agents drive the cohort builder: Claude Code
and its subagents, a managed agent, or any MCP client. It exposes the
following tools, in the order an agent typically uses them:

1. `list_datasources`: Aurora databases, S3 folders, BigQuery datasets
   and views-only DuckDB catalogs.
2. `list_tables`: tables, data files or catalog views (with their SQL).
3. `open_dataset`: load a table (up to the row cap) and return a
   `dataset_id` and column profile.
4. `query_dataset`: cross-filtered counts and a page of rows.

The MCP server can't change the UI or write data. On a Workbench VM the
public URL is behind the app proxy, which needs browser cookies, so
connect from inside the workspace (`http://localhost:8080/mcp` on the
VM, or a port-forward). The `mcp` package is optional; without it the
app runs and `/mcp` isn't mounted. Example for Claude Code:

```bash
claude mcp add --transport http cohort-studio http://localhost:8080/mcp
```

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

## Joining datasets

Joins work like Metabase's notebook editor. Open the **Join** panel on a
loaded dataset (the base), then add up to 6 steps. Each step joins one
more open dataset onto the result so far:

- **Join type**, shown as a Venn diagram: `inner`, `left`, `right`,
  `full`, `semi` (keep base rows that have a match) or `anti` (keep base
  rows with no match). Semi and anti answer "has a visit" and "has no
  visit" questions and add no columns.
- **Conditions**: one or more, combined with AND, each using `=`, `!=`,
  `<`, `<=`, `>` or `>=`. If the two key columns have different types,
  `=` and `!=` compare them as text and the preview says so. Other
  operators need matching types.
- **Columns**: choose which columns of the joined table to bring in.
  They are named `<alias> → <column>`.
- **Suggestions**: likely key pairs, found by matching names (including
  `id` ↔ `<table>_id`) and scored by how many base values appear on the
  other side.
- **Shared key** applies one common column to all selected join steps.
- **Table pickers** are searchable: type to filter, arrow keys to move,
  Enter to choose, Escape to close.

**Where the join runs.** A badge in the panel shows the engine:

- **Aurora** for compatible tables and live join results from the same Aurora
  resource. Queries operate on the full source; only the preview is capped.
  Counts, filters, charts and pages continue to run on Aurora.
- **In memory** uses DuckDB over loaded S3, BigQuery, catalog, upload or derived
  frames, and tables from different databases. Capped inputs are marked.
  A live Aurora result cannot be mixed with another resource or silently
  converted to its capped preview.

**Checks before and during a run.** The panel validates the steps as you
edit them and shows problems on each condition: unknown columns, types
that can't be compared, and keys compared as text. **Preview** shows the
row count before and after each step and a 20-row sample, and warns when
a step more than doubles the rows, which usually means a non-unique key.
On Aurora, preview counts stop after 10 s with an error. A full run
stops after 40 s. Original table inputs may fall back to loaded frames with
an explicit note. Live Aurora inputs never fall back to preview data.

**Join into new tab** opens a capped preview and reports the engine and full
join count. Aurora results keep their full query source. Select **Count unique**
to show distinct non-null person or entity IDs separately from rows.

**Saved views** can restore joins from their table resources, conditions and
column settings. **Column settings** changes number/text behavior, filter kind
and labels. Invalid numeric values anywhere in an Aurora column reject the
change. A derived column on an Aurora source can be restored from its base
recipe and validated operation. Uploaded files cannot be restored as sources.

**Large results and caching.** Explore warns at 100,000 rows and marks capped
previews. Aurora query results are cached in memory for 30 seconds, with a
visible fetch time. **Refresh data** bypasses the cache and refreshes filter
choices. The cache holds at most 64 entries and 32 MiB of serialized payload;
entries above 4 MiB are not cached. Set `STUDIO_QUERY_CACHE_TTL` to 0 to disable
it, or to a value up to 300 seconds. Compare and derive operate on the full
Aurora source; derived columns remain database-backed and their saved views
store a validated operation, not SQL. Dataset chat remains available only for
loaded rows.

**Export TSV** on a database-backed tab runs as a background job. It streams
Aurora rows to a temporary file, reports progress, supports cancellation, and
offers a download after completion. Limits are 2 concurrent workers, 8
retained jobs, 2 GiB per file and 4 GiB total. Finished jobs expire after 1
hour; each job has a 30-minute runtime limit and a 5-minute database statement
timeout. Temporary files use local app-container disk. The older synchronous
export, materialization and S3 workflow export still cap at 100,000 rows.
Studio adds no database service or schema for exports.

Studio uses Aurora storage and internal DuckDB; it does not deploy a separate
PostgreSQL service. A disposable PostgreSQL process is only a local test fixture
for Aurora-compatible SQL and driver checks.

API: `POST /api/datasets/join`, `POST /api/datasets/join/preview`,
`POST /api/datasets/join/validate`, `GET /api/datasets/join/suggest`.
Code: `app/joins.py`.

## Development

```bash
# Backend (terminal 1)
cd src/cohort-studio
UV_CACHE_DIR=/tmp/studio-uv-cache uv venv .venv
UV_CACHE_DIR=/tmp/studio-uv-cache uv pip install --python .venv/bin/python -r app/requirements.txt
cd app && UV_CACHE_DIR=/tmp/studio-uv-cache uv run --no-project --python ../.venv/bin/python python -m uvicorn main:app --reload --port 8080

# Frontend with hot reload (terminal 2) — proxies /api to :8080
cd src/cohort-studio/web
npm install && npm run dev
```

No workspace needed locally — upload a CSV from the sidebar.

### Testing

```bash
cd src/cohort-studio
UV_CACHE_DIR=/tmp/studio-uv-cache uv pip install --python .venv/bin/python pytest httpx pytest-playwright
UV_CACHE_DIR=/tmp/studio-uv-cache uv run --no-project --python .venv/bin/python python -m playwright install chromium
cd web && npm run build && mkdir -p ../app/static && cp -R dist/. ../app/static/ && cd ..
UV_CACHE_DIR=/tmp/studio-uv-cache uv run --no-project --python .venv/bin/python python -m pytest
UV_CACHE_DIR=/tmp/studio-uv-cache uv run --no-project --python .venv/bin/python python -m pytest -m e2e
```

The suite keeps browser/MCP flows, HTTP outcomes, real database operations,
and updater-process checks. Implementation unit tests are removed. Some HTTP
tests replace cloud/model calls; they do not prove live provider or Workbench
access. OMOP tests require PostgreSQL binaries (`STUDIO_PG_BIN` can set their
location). Use the full suite for releases; `-m e2e` selects the browser/MCP flows.

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

For a browser-isolated deployment, where users see Studio only through a
streamed Chromium session and can't download data, use
[../virtual-browser-cohort-studio](../virtual-browser-cohort-studio/)
instead. It runs this same image.

### In-app updates

App code is baked into the image at VM creation, but this app
self-updates: `self_update.sh` (in the image) fetches the branch tarball
from GitHub, stages and validates the backend, rebuilds the frontend, and
replaces the running app files. The script stops uvicorn and Compose restarts
the container on the new files. This in-app update does not recreate the
Workbench app or VM. The operation is a no-op when the branch has not moved.

- **Restart the VM** → `postStartCommand` runs the script → latest
  branch is live in ~1 minute.
- **Update in the running app**: `POST <app-url>/api/admin/update`, then poll
  `GET /api/version` until the sha changes. Progress lands in
  `/tmp/self-update.log` inside the container.

An app/VM rebuild is only needed when `.devcontainer.json`, the Dockerfile,
or the compose file change.

## Datasources

### OMOP CDM

Choose **OMOP cohorts**, then select an Aurora resource. Search concepts, add
criteria, set timing and demographics, and click **Count cohort**. Counts and
attrition query the full database. **Open cohort** loads matching people into
Explore. **Open clinical table** loads events, optionally restricted to the
cohort and enriched with concept names. Open datasets use the app row cap.

The first included criterion defines the index date. Before/after relations are
strict. Concepts within a criterion use OR; criteria use AND. Age is index year
minus birth year. Spec edits clear the displayed count.

The **Cohort assistant** searches concepts and proposes validated criteria. It
also reads workflow and app status. Review the proposal, click **Apply proposed
cohort**, then Count/Open. It has no workflow or app mutation tools. Select the
AI provider in Settings. OMOP definitions remain session state and are not
restored by Saved views.

Browser and MCP tests use a real temporary PostgreSQL fixture. Real Aurora,
resource-based loading, and full-size vocabulary performance still need
workspace validation. See [project state](docs/PROJECT_STATE.md) for exact test
results and release status.

#### Load an OMOP export from S3 into Aurora

Run from the Workbench app container, where the CLI has resource credentials
and the network can reach Aurora. The importer stages files from a Workbench S3
resource, then uses PostgreSQL COPY into Aurora in one transaction. It does not
require an Aurora S3 extension or a new cluster IAM role.

```sh
cd /app
python -m omop_load \
  --resource-id <aurora-resource-id> \
  --schema cdm_source_name \
  --s3-resource-id <s3-folder-resource-id> \
  --s3-path exports/omop/
```

Use a relative ZIP key instead of a prefix for a ZIP export. Local development
can use `uv run --no-project --python .venv/bin/python python -m omop_load`
with `PYTHONPATH=app` from this directory. Studio currently detects one CDM per
Aurora resource; use separate Aurora resources for sources that must be selected
independently. Loading several CDM schemas into one database does not add a
schema selector to the UI.
An existing CDM is kept unless `--replace` is supplied; that option drops the
target schema. Temporary staged files are removed after the command ends.

Input must be a self-contained OMOP CSV export: `person`, `observation_period`,
at least one clinical domain table, `concept`, and `concept_ancestor`.
Nested CSV and CSV.gz files are supported. Duplicate table files are rejected.
This command does not convert raw CMS claims, Parquet, or BigQuery tables to
OMOP. CMS SynPUF is one possible source, but its collection link does not supply
an S3 path. The actual resource and export format must be identified first.

This is a CLI import path. Live S3-to-Aurora validation is still pending; the
current machine cannot reach the dev Aurora endpoint.

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
