# MDV — Multi-Dimensional Viewer custom app

A Workbench custom application that runs [MDV](https://github.com/Taylor-CCB-Group/MDV)
(Multi-Dimensional Viewer) — a web app for visualising spatial and molecular data.

- Using the app: [USER-GUIDE.md](USER-GUIDE.md).
- Testing in Workbench: [WORKBENCH-TESTING.md](WORKBENCH-TESTING.md).

## Architecture

MDV is not a single-container app. It ships as two coupled services:

| Service  | Image               | Role                                                                 |
| -------- | ------------------- | ------------------------------------------------------------------- |
| `app`    | `mdvadmin/mdv:stable` (pinned by digest) | nginx on **5055** in front of Flask + gunicorn (loopback `5056`), serving the built React frontend. Runs as user **`pn`**. Also runs the workspace data sync. |
| `mdv_db` | `postgres:16`       | Stores project metadata, including filesystem paths to each project. |

The `app` service is the Workbench primary container (`container_name:
application-server`) and joins the external `app-network`. `mdv_db` sits on a
**private** `mdv-internal` network with no host port exposed; only `app` can
reach it. `app` waits for the database healthcheck before starting.

### Cross-origin isolation (`SharedArrayBuffer`)

MDV's data loaders and worker threads need `SharedArrayBuffer`, which browsers
only expose to a cross-origin isolated document. Workbench embeds custom apps in
an iframe inside a console page that isn't itself isolated, so MDV's own
`COOP`/`COEP` headers aren't enough on their own (and its client-side
`coi-serviceworker` fallback forces a reload on first visit — costly for large
datasets). [`start.sh`](start.sh) runs MDV's gunicorn on loopback `127.0.0.1:5056`
and puts nginx ([`nginx.conf.template`](nginx.conf.template)) in front of it on
`5055`, adding `Document-Isolation-Policy` on every response. This isolates MDV's
document without requiring the embedding frame chain to be isolated, and without
any reload. See BENCH-9901.

`MDV_ISOLATION_MODE` selects the policy (`docker-compose.yaml`):

| Mode | Headers on MDV's document | Cross-origin resources |
| --- | --- | --- |
| `credentialless` (default) | `Document-Isolation-Policy: isolate-and-credentialless`, `Cross-Origin-Embedder-Policy: credentialless` | Public files and images load even without CORP headers; requests are sent without cookies. |
| `require-corp` | `Document-Isolation-Policy: isolate-and-require-corp`, `Cross-Origin-Embedder-Policy: require-corp` | Load only if the host sends `Cross-Origin-Resource-Policy` or CORS headers. |

In both modes, data that MDV **reads with JavaScript** (`fetch`, workers) from
another site still needs that site to send CORS headers (most public data hosts
do, e.g. public GCS buckets and EBI). Workspace data is served from MDV's own
origin, so it needs nothing extra.

MDV's Flask app always sends `Cross-Origin-Embedder-Policy: require-corp`, and the
browser enforces COEP and DIP together, so nginx replaces MDV's COEP header to
match the mode. With DIP alone set to `credentialless`, public images without
CORP headers are still blocked (verified in Chromium 141).

Browser support: Document-Isolation-Policy is supported in Chrome and Edge 137+
(desktop) and Chrome 146+ on Android. Firefox and Safari don't support it yet; in
those browsers MDV fails to load data with `SharedArrayBuffer is not defined`.

## Workspace data

Users open data from the workspace's buckets without uploading it, in two ways.
Either way, the app links or converts the data directly from the bucket mount, so
large files never go through the browser or the Workbench proxy.

**1. The Workspace data button (on demand).** A **Workspace data** button in the
bottom-right corner of every MDV page opens a browser of the workspace's mounted
buckets. Users go to any folder and click **Open** next to a file or MDV project;
MDV opens the result when it's ready (seconds for small files, minutes for large
ones). Opening the same item again goes straight to the existing project.

**2. The `mdv/` folder (automatic).** Anything in a folder named `mdv` at the top
of a bucket appears in MDV's catalog at app start and every 10 minutes:

| Put this in a bucket | MDV shows |
| --- | --- |
| `mdv/projects/<name>/` — an MDV project folder (has `datasources.json`) | Project `<bucket>--<name>` |
| `mdv/data/<file>` — a supported file (below) | Project `<bucket>--<file name>` |

| Supported | How it's opened |
| --- | --- |
| MDV project folder (has `datasources.json`), e.g. made with `mdvtools convert-scanpy` or exported from MDV and unzipped | Linked in place; data isn't copied |
| AnnData `.h5ad`, MuData `.h5mu` | Converted (`mdvtools` `convert_scanpy_to_mdv` / `convert_mudata_to_mdv`) |
| VCF `.vcf`, `.vcf.gz` | Converted (`convert_vcf_to_mdv`), with a genome browser track |
| Tables `.csv`, `.tsv`, optionally `.gz` | Converted to a single-table project |

Converted projects are written to the app's disk; the bucket isn't changed. `<bucket>`
is the bucket's Workbench resource name, prefixed by its Workbench folder path if it's
in a folder.

How it works ([`workspace-sync/`](workspace-sync/)):

- [`start-workspace-sync.sh`](workspace-sync/start-workspace-sync.sh) runs from
  `postStartCommand` after `remount-on-restart.sh`. It bind-mounts each mounted bucket
  **read-only** under `/mnt/mdv-workspace-ro/<bucket>`, so MDV can never modify bucket
  data, even for writable controlled buckets.
- [`mdv_workspace_sync.py`](workspace-sync/mdv_workspace_sync.py) creates one folder per
  project under MDV's projects directory (`/app/mdv`) and registers new projects with MDV
  (`/rescan_projects`). For linked projects, data files are symlinks into the read-only
  mount and directories are local; the small files MDV edits (`views.json`, `state.json`,
  `datasources.json`, `README.md`) are local copies, so saving views works.
  [`convert_file.py`](workspace-sync/convert_file.py) does conversions with MDV's Python.
- [`workspace_ui.py`](workspace-sync/workspace_ui.py) (on `127.0.0.1:5057`, routed by
  nginx at `/_workspace/`) serves the Workspace data browser. It lists only the read-only
  mounts and rejects paths outside them. When a user opens an item, it records it in
  `/app/mdv/.workspace-imports.json` and runs the sync for that item. nginx adds
  [`workspace-ui.js`](workspace-sync/workspace-ui.js) to MDV's HTML pages (`sub_filter`).
- [`workspace-sync-loop.sh`](workspace-sync/workspace-sync-loop.sh) repeats the sync every
  `MDV_SYNC_INTERVAL_MINUTES` to pick up new or changed data.
- When a source is deleted from a mounted bucket, its project is removed from MDV.
  Nothing is removed just because a bucket isn't mounted.

Actions that change a linked project's data (add datasource, add or combine AnnData,
add images) fail, because the data is read-only. Saving views and layouts works.
To change the data, update it in the bucket.

Why not the Workbench SDK file picker: it intercepts MDV's file inputs, but delivers the
selected files to the browser (the SDK docs note large selections cause memory
pressure), and MDV would then upload them back through the Workbench proxy in 256 KB
chunks. That's two slow passes for multi-GB omics files, it doesn't cover drag-and-drop
or existing MDV projects, and it needs Node.js 24 in the image (MDV's has 22).

### Sample data

If no mounted bucket has MDV data (`MDV_SAMPLE_DATA=auto`), MDV opens with sample
projects instead. They're removed automatically once workspace data appears.

| Sample | Size | Available |
| --- | --- | --- |
| `sample--pbmc3k-processed` — Scanpy `pbmc3k_processed`, the dataset in MDV's quickstart | 2,638 cells × 1,838 genes | Immediately; built into the image |
| `sample--1000genomes-chr1-variants` — 1000 Genomes phase 3 chromosome 1 variants, the example in MDV's backend tools tutorial | Up to all 6.47 million variants, scaled to the VM's memory (`MDV_SAMPLE_VCF_MAX_SITES`); the full set needs about 3.2 GB to convert | After a background download (1.2 GB) and conversion on first start; kept on the `mdv-samples` volume |

## Data & persistence

MDV keeps two coupled stores that must stay in sync:

- **Project files** (project directories + `.h5` data) on the `mdv-data` volume
  mounted at `/app/mdv`. Linked workspace projects hold only symlinks and small
  metadata files here.
- **Project metadata** in PostgreSQL on the `postgres-data` volume.

Do not move either store onto a gcsfuse bucket — MDV's random/mmap `.h5` writes
and PostgreSQL's data directory are not compatible with gcsfuse. Reading linked
project data from a bucket is fine.

## Authentication

Access is gated by Workbench, so MDV's own auth is disabled
(`ENABLE_AUTH=0`). If in-app identity is ever required, MDV supports
Auth0-federated OIDC.

## Configuration

Settings in `docker-compose.yaml` (`app` service `environment`):

| Variable | Default | Effect |
| --- | --- | --- |
| `MDV_ISOLATION_MODE` | `credentialless` | Cross-origin isolation mode; see above. |
| `MDV_WORKSPACE_FOLDER` | `mdv` | Folder in each bucket that holds MDV data. |
| `MDV_WORKSPACE_CONVERT` | `true` | Convert supported files (from `<bucket>/mdv/data/` or the Workspace data button). |
| `MDV_SYNC_INTERVAL_MINUTES` | `10` | Minutes between syncs; `0` = only at app start. |
| `MDV_SAMPLE_DATA` | `auto` | `auto` (only when no bucket has MDV data), `always` or `never`. |
| `MDV_SAMPLE_VCF_MAX_SITES` | `0` | Variants in the large sample; `0` = as many as memory allows. |

Database credentials use docker-compose variable substitution with test defaults.
To override, copy `.env.example` to `.env` and set real values:

```bash
cp .env.example .env
# edit .env
```

`.env` is git-ignored. For a production deployment, supply `FLASK_SECRET_KEY` and
database credentials as secrets rather than committed defaults.

The image is pinned to the digest of `mdvadmin/mdv:stable` as of 2026-11-10
(built 2026-03-23). `start.sh` runs that image's `poetry run gunicorn`; newer MDV
images use `uv run`, so update `start.sh` when moving the pin.

## Logs

- Workspace sync and imports: `/var/lib/mdv-workspace-sync/sync.log` in the
  `application-server` container, also at `<app URL>/_workspace-sync.log`.
- MDV and nginx: `docker logs application-server`.

## Ports

- **5055** — MDV web UI (forwarded and surfaced by the Workbench UI).

## Local test

```bash
docker network create -d bridge app-network
devcontainer up --workspace-folder src/mdv
./tests/mdv.sh
```
