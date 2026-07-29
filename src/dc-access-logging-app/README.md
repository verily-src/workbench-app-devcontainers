# Data Collection Access Logging

A Flask web app for auditing data collection access grants in Verily Workbench. It queries BigQuery monitoring tables to show who has access, through which groups, and when access was granted.

## Tabs

### Forensic: Data Collection (landing page)

Look up a data collection by ID. Shows the full history of access grants, including:

- **GROUP** rows: a group was granted access to the data collection. Click the **expand arrow** (&#9654;) to see all members who were already in the group at the time of the grant.
- **MEMBER** rows: an individual who was added to a group after the group was granted access, or removed from a group after the group was granted access.
- **INDIVIDUAL** rows: a user granted access directly.
- **DC Role**: displays the role conferred at the time of the grant (e.g. READER, WRITER, DISCOVERER, OWNER, APPLICATION). If access has since been revoked, the revocation timestamp is shown in red beneath the role.

Use the **Group Name / Internal Name** toggle above the table to switch between showing the user-facing group name and the internal group identifier.

Use the **Hide revoked** checkbox to exclude rows where access has been revoked.

### Group Membership Audit

Look up a group by its user-facing name. Shows the full history of membership changes — all grants and revocations from the activity log, including timestamps, who acted, and the reason.

Use the **Current members only** checkbox to show only users who currently hold membership (hides all rows for users whose latest action is a revocation).

## Org Override

All tabs include an optional **Org Override** field. By default the app uses the org configured in `config.yaml` or the `DC_ACCESS_ORG_UFID` environment variable (shown in the field's hint text). Enter a different org ID to query that org's tables instead — useful for looking up data collections across orgs without restarting the app.

## Search Persistence

When you search for a data collection on the Forensic tab, switching to another tab automatically carries over the search value and org override so you don't have to re-type them.

## Table Features

All result tables support:

- **Keyword filter**: enter one or more space-separated keywords in the filter box. Toggle between **AND** (all keywords must match) and **OR** (any keyword matches) using the segmented toggle next to the filter box.
- **Column filters**: click an underlined column header to filter results by specific values. Use the sort arrow to reorder rows.
- **Sort**: click the sort arrow on any column header to sort ascending/descending.
- **Resize**: drag the right edge of any column header to adjust width.

## Configuration

The app reads configuration in this order (first match wins):

| Setting | Env Var | `config.yaml` key | Fallback |
|---|---|---|---|
| Environment | `DC_ACCESS_ENV` | `env` | `prod` |
| BigQuery data project | `DC_ACCESS_BQ_PROJECT` | `bq_project` | *(none)* |
| BigQuery job project | `DC_ACCESS_JOB_PROJECT` | `job_project` | `wb workspace describe` |
| Organization | `DC_ACCESS_ORG_UFID` | `org` | `wb workspace describe` |

- **`bq_project`** — the project that hosts the monitoring tables (e.g. `workbench-bq-log-sink`). Used in SQL table references like `` `workbench-bq-log-sink.workbench_monitoring_org_logs_prod.…` ``.
- **`job_project`** — the project where BigQuery jobs are executed and billed. On Workbench, this is automatically resolved to the workspace's Google project. You typically don't have `bigquery.jobs.create` permission on the data project, so jobs must run in your own project.

Example `config.yaml`:

```yaml
env: "prod"
bq_project: "workbench-bq-log-sink"
org: "demo"
```

The **org** value determines the table suffix. When set (e.g. `demo`), the app queries org-specific tables like `data_collection_access_grants_demo`. When empty, tables have no suffix.

## Running Locally

```bash
cd app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask run --host 0.0.0.0 --port 5000
```

Open http://localhost:5000. You need valid GCP credentials with access to the `workbench-bq-log-sink` BigQuery project.

## Running on Workbench

The app runs as a devcontainer via `docker-compose.yaml`. Caddy serves as a reverse proxy on port 8080, forwarding to the Flask app on port 5000.

The org is automatically resolved from `wb workspace describe` if not set via env var or config.

Environment variables can be set in the `docker-compose.yaml` or passed at launch:

```bash
DC_ACCESS_ENV=prod DC_ACCESS_ORG_UFID=demo docker-compose up
```
