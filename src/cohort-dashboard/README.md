# Cohort Dashboard

No-code cohort exploration dashboard for tabular data in Aurora PostgreSQL — a
Python-native sibling of [Cohort Explorer](../cohort-explorer/), built with
[Panel](https://panel.holoviz.org/) + HoloViz instead of FastAPI + React.

## Design

One idea drives the architecture: **every datasource is a SQL query away.**

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

There is no seeding pipeline, no dynamic ORM model, and no React build step:
Panel serves the whole UI from Python, loading a table auto-generates the
chart dashboard, and filters/charts react live with no Apply button.

```
src/cohort-dashboard/
├── Dockerfile                  # python-only image; CMD = panel serve
├── docker-compose.yaml         # container config (host: application-server)
├── devcontainer-template.json  # Workbench app template
└── app/
    ├── main.py       # the entire Panel UI
    ├── db.py         # wb resource resolve + engine/connection caching
    ├── queries.py    # SQL layer: tables, fetch, foreign-table DDL, filter inference
    └── tests/        # pytest unit tests
```

## Requirements for the S3 path

`aurora_analytics` needs cluster-level provisioning that Workbench controls:

- Aurora PostgreSQL **17.11+** (the aurora-resource-demo cluster is 16.9)
- cluster parameter `aurora_analytics.enabled = true`
- an IAM role attached to the cluster with `--feature-name AuroraAnalytics`
  and S3 read access
- an S3 gateway VPC endpoint if the cluster is in a private subnet

The app detects whether the extension is available and the "Register S3 data"
action fails with a clear error when it is not. Native tables and views work
on any cluster version.

## Local development

No workspace needed — upload a CSV/TSV in the sidebar to explore local data.

```bash
cd src/cohort-dashboard/app
pip install -r requirements.txt -r requirements-dev.txt
panel serve main.py --port 8080 --dev
```

Aurora access additionally requires an authenticated `wb` workspace context
and VPC network access (cloud workstation in-region; not from a laptop).

### Testing

Coverage is end-to-end first: pytest + Playwright boot a real `panel serve`
process, upload a CSV fixture through the browser, and assert that the grid,
filters, counts, and charts respond. A few unit tests guard the SQL
identifier/DDL validation in `queries.py`.

```bash
cd src/cohort-dashboard
pip install -r app/requirements-dev.txt
playwright install chromium   # one-time browser download
python3 -m pytest             # everything
python3 -m pytest -m "not e2e"  # just the fast unit tests
```

## Deploying

```bash
wb app config create \
  --name="Cohort Dashboard" \
  --git-repo-url="https://github.com/verily-src/workbench-app-devcontainers.git" \
  --git-branch="cohort-dashboard" \
  --dev-container-path="src/cohort-dashboard" \
  --description="No-code cohort exploration over Aurora, including S3 data via aurora_analytics"
```

Then create the app from the Workbench UI.

**Note:** Panel needs a WebSocket connection (unlike Cohort Explorer's plain
HTTP). JupyterLab runs over WebSockets behind the same app proxy, so this is
expected to work — verify it first on a real VM. The VM-debugging rules in
[../cohort-explorer/CLAUDE.md](../cohort-explorer/CLAUDE.md) apply to this app
unchanged.

## Lineage / audit (planned)

Loads, S3 registrations, exports, and cohort saves will be recorded as events;
storage backend under evaluation (DynamoDB vs. Aurora tables vs. S3 event log).
