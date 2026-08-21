# MDV — Multi-Dimensional Viewer custom app

A Workbench custom application that runs [MDV](https://github.com/Taylor-CCB-Group/MDV)
(Multi-Dimensional Viewer) — a web app for visualising spatial and molecular data.

## Architecture

MDV is not a single-container app. It ships as two coupled services:

| Service  | Image               | Role                                                                 |
| -------- | ------------------- | ------------------------------------------------------------------- |
| `app`    | `mdvadmin/mdv:stable` | Flask + gunicorn backend serving the built React frontend on **5055**. Runs as user **`pn`**. |
| `mdv_db` | `postgres:16`       | Stores project metadata, including filesystem paths to each project. |

The `app` service is the Workbench primary container (`container_name:
application-server`) and joins the external `app-network`. `mdv_db` sits on a
**private** `mdv-internal` network with no host port exposed; only `app` can
reach it. `app` waits for the database healthcheck before starting.

## Data & persistence

MDV keeps two coupled stores that must stay in sync:

- **Project files** (project directories + `.h5` data) on the `mdv-data` volume
  mounted at `/app/mdv`.
- **Project metadata** in PostgreSQL on the `postgres-data` volume.

Both use local named Docker volumes. Do not move either store onto a gcsfuse
bucket — MDV's random/mmap `.h5` writes and PostgreSQL's data directory are not
compatible with gcsfuse. Use a bucket for backups/exports only.

## Authentication

Access is gated by Workbench, so MDV's own auth is disabled
(`ENABLE_AUTH=0`). If in-app identity is ever required, MDV supports
Auth0-federated OIDC.

## Configuration

Credentials use docker-compose variable substitution with test defaults. To
override, copy `.env.example` to `.env` and set real values:

```bash
cp .env.example .env
# edit .env
```

`.env` is git-ignored. For a production deployment, pin the MDV image to a
specific digest and supply `FLASK_SECRET_KEY` and database credentials as
secrets rather than committed defaults.

## Ports

- **5055** — MDV web UI (forwarded and surfaced by the Workbench UI).

## Local test

```bash
docker network create -d bridge app-network
devcontainer up --workspace-folder src/mdv
./tests/mdv.sh
```
