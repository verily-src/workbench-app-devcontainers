# Cohort Studio — architecture & flows

Diagrams for how the app is put together and how the two non-obvious
flows (restart-to-deploy "Update", and a state round-trip) work. Render
with any Mermaid-aware viewer (GitHub renders these inline).

## 1. Overall architecture

```mermaid
flowchart TB
  subgraph Browser["Browser (React + TS + ECharts)"]
    UI["App.tsx — tabs, filters, charts<br/>DatasetPane · ChartCard · ChatWidget"]
  end

  subgraph VM["Workbench VM — Docker container (restart: always)"]
    subgraph API["FastAPI (uvicorn, PID 1)"]
      EP["/api/* endpoints"]
      STORE["datasets.py<br/>in-memory DataFrame store<br/>+ server-side cross-filter aggregation"]
      AGENT["agent.py · llm.py<br/>Anthropic SDK (chat + Ask AI)"]
      VIEWS["views.py · config.py<br/>saved views, settings"]
      LIN["lineage.py<br/>_lineage_event table"]
      MCPS["mcp_server.py<br/>MCP server mounted at /mcp"]
    end
    SU["self_update.sh"]
  end

  subgraph Data["Workspace datasources"]
    AUR[("Aurora PostgreSQL")]
    S3[("S3 — Parquet/CSV<br/>via DuckDB")]
    BQ[("BigQuery")]
  end

  ANT["Anthropic API"]
  GH["Branch tarball (git host)"]

  UI -->|"fetch /api/*"| EP
  EP --> STORE
  EP --> AGENT
  EP --> VIEWS
  EP --> LIN
  AGENT --> ANT
  STORE -->|"wb resource resolve"| AUR
  STORE -->|"credential_process profile"| S3
  STORE --> BQ
  VIEWS --> AUR
  VIEWS --> S3
  LIN --> AUR
  SU -->|"fetch + rebuild"| GH
```

Credential model: Aurora creds come from `wb resource resolve` (ABAC,
per-resource); S3 access uses a `credential_process` AWS profile wired by
`wb workspace configure-aws`, exported into a DuckDB `SECRET ... PROVIDER
config` (DuckDB can't run `credential_process` itself).

## 2. Restart-to-deploy — what "Update" does

The container runs uvicorn as PID 1 under `restart: always`. Updating is:
pull the branch, rebuild the frontend, then kill PID 1 so Docker restarts
it on the new code. No VM recreate.

```mermaid
sequenceDiagram
  participant U as User
  participant API as FastAPI (old code)
  participant SU as self_update.sh
  participant GH as Branch tarball
  participant D as Docker daemon

  U->>API: POST /api/admin/update
  API->>SU: spawn script
  SU->>GH: download branch tarball
  SU->>SU: unpack over app, npm build, copy dist→app/static
  SU->>API: pkill uvicorn (PID 1)
  Note over API,D: container exits
  D->>API: restart (restart: always) on new code
  U->>API: reload — new version served
```

## 3. One state round-trip (filter / chart change)

The frontend is thin: it sends the current filter set and the charts it
is showing; the server returns counts, per-chart aggregates (full and
filtered cohort), and one page of rows — everything for a render in a
single call. All statistics stay server-side.

Aggregation has two interchangeable backends behind the same response
shape: pandas (`datasets.py`) for small frames, and DuckDB SQL over the
in-memory frame (`agg_duck.py`) once row count crosses
`STUDIO_DUCKDB_AGG_ROWS` (default 50k). The DuckDB path pushes filtering,
group/count, binning and paging into a vectorised columnar engine; parity
tests pin its output to the pandas path, and any DuckDB error falls back
to pandas rather than failing the query.

```mermaid
sequenceDiagram
  participant UI as Browser
  participant API as /api/query
  participant DS as datasets.py

  UI->>API: { dataset_id, filters[], chart_specs[], page }
  API->>DS: apply_filters(full, filters)
  DS->>DS: chart_aggregate(full, filtered, spec) per chart
  DS->>DS: page of rows
  API-->>UI: { total, filtered, charts[], rows{} }
  UI->>UI: ECharts renders "all" vs "selected" per chart
```

## 4. Saved views / state persistence

A saved view captures every open tab (datasource-backed ones — uploads
can't be reloaded) with its filters and charts, into Aurora (a
`_studio_views` row) or S3 (a JSON object), so state survives the app
closing. The in-memory DataFrame store is reconstructed by re-opening
each tab's datasource on load.
