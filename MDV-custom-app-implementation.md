# MDV Custom App — Implementation Details

Companion to [MDV-custom-app-advisory.md](MDV-custom-app-advisory.md). The advisory covers *why*;
this doc captures *what was built* in `src/mdv/` and how to run and test it.

Source project: [Taylor-CCB-Group/MDV](https://github.com/Taylor-CCB-Group/MDV)
Prepared for: Oxford IMCM (enterprise Verily Workbench customer)

## What was built

A two-service Verily Workbench custom app under [src/mdv/](src/mdv/), following the multi-service
`src/playground` precedent (web front + private Postgres backend).

| File | Purpose |
| --- | --- |
| [src/mdv/docker-compose.yaml](src/mdv/docker-compose.yaml) | Two services: `app` (MDV, the Workbench-facing `application-server`) and `mdv_db` (PostgreSQL). Defines named volumes and networks. |
| [src/mdv/.devcontainer.json](src/mdv/.devcontainer.json) | Devcontainer config: `service: app`, Workbench startup hooks, features, `remoteUser: root`. |
| [src/mdv/devcontainer-template.json](src/mdv/devcontainer-template.json) | Template metadata and `cloud` / `login` options consumed by the build harness. |
| [src/mdv/.env.example](src/mdv/.env.example) | Template for DB credentials and `FLASK_SECRET_KEY`. Copy to `.env` (git-ignored). |
| [src/mdv/.gitignore](src/mdv/.gitignore) | Keeps `.env` out of version control. |
| [src/mdv/README.md](src/mdv/README.md) | App-level documentation. |
| [tests/mdv.sh](tests/mdv.sh) | Smoke test: standard base checks + MDV-specific checks. |
| [.github/workflows/test-pr.yaml](.github/workflows/test-pr.yaml) | `mdv` registered in the CI matrix (with `maximize_build_space`). |

## Service topology

```
                 app-network (external, Workbench-facing)
                          │
                   ┌──────┴───────┐
                   │     app      │  container_name: application-server
                   │  MDV :5055   │  image: mdvadmin/mdv:stable  (user: pn)
                   └──────┬───────┘
                          │  mdv-internal (private; no host port)
                   ┌──────┴───────┐
                   │    mdv_db    │  image: postgres:16
                   │   Postgres   │  healthcheck: pg_isready
                   └──────────────┘

volumes:  mdv-data → /app/mdv                (projects + .h5 files)
          postgres-data → /var/lib/postgresql/data   (project metadata)
```

- Only `app` joins the external `app-network` and carries `container_name: application-server`.
- `mdv_db` sits on the private `mdv-internal` network with **no host port exposed** — reachable by
  `app`, invisible to Workbench and the outside.
- `app` gates startup on the DB healthcheck via `depends_on: { condition: service_healthy }`.

## Key configuration decisions (as implemented)

| Concern | Decision | Where |
| --- | --- | --- |
| Image | Prebuilt `mdvadmin/mdv:stable` (pin a digest for prod) | `docker-compose.yaml` |
| Auth | `ENABLE_AUTH=0` — access gated by Workbench | `docker-compose.yaml` env |
| Persistence | Local named volumes (`mdv-data`, `postgres-data`) — Option A | `docker-compose.yaml` volumes |
| DB isolation | Private `mdv-internal` network, no host port | `docker-compose.yaml` networks |
| Credentials | Compose variable substitution with test defaults; override via `.env` | `.env.example` |
| Container user | `pn`, home `/home/pn` | `.devcontainer.json` hook args |
| Port | 5055 | `docker-compose.yaml` ports |

### Environment variables (app service)

| Variable | Value | Notes |
| --- | --- | --- |
| `FLASK_ENV` | `production` | |
| `DB_HOST` | `mdv_db` | matches the db service name |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | from `.env` (defaults `mdv_user` / `mdv_password` / `mdv_db`) | shared with `mdv_db` |
| `FLASK_SECRET_KEY` | from `.env` (default placeholder) | set a real random value for prod |
| `MDV_API_ROOT` | `/` | revisit if Workbench serves the app under a subpath |
| `ENABLE_AUTH` | `0` | Workbench-gated |

## Devcontainer wiring

- `service: app`, `workspaceFolder: /workspace`, `shutdownAction: none`, `runServices: [app, mdv_db]`.
- `postCreateCommand` → `./startupscript/post-startup.sh pn /home/pn ${templateOption:cloud} ${templateOption:login}`.
- `postStartCommand` → `./startupscript/remount-on-restart.sh` with the same args.
- Features: `java`, `aws-cli`, `google-cloud-cli` (parity with `src/example`).
- `remoteUser: root`.

## How to run locally

Prerequisites: Docker, Node.js/npm, and the two CLIs your test run was missing (see below).

```bash
cd /home/user/repos/workbench-app-devcontainers

# app-network is shared; create it only if it doesn't already exist
docker network inspect app-network >/dev/null 2>&1 || docker network create -d bridge app-network

# optional: real credentials
cp src/mdv/.env.example src/mdv/.env   # then edit

devcontainer up --workspace-folder src/mdv
./tests/mdv.sh
```

## Smoke test

[tests/mdv.sh](tests/mdv.sh) runs as `TEST_USER=pn` and checks:

1. `tests/common/base.bats` — `gcsfuse`, `wb` CLI, and `fuse.conf` `user_allow_other`.
2. MDV responds on `http://localhost:5055/` inside the container.
3. `mdv_db` is resolvable from the app container (private network wired).

### Required tooling (fixes for the errors seen)

The failed run was missing host tools, not app problems:

| Error | Cause | Fix |
| --- | --- | --- |
| `network with name app-network already exists` | Harmless — network was already created | Ignore, or guard with `docker network inspect ... || docker network create` |
| `devcontainer: command not found` | Devcontainer CLI not installed | `npm install -g @devcontainers/cli` |
| `bats: command not found` | BATS test runner not installed | Debian/Ubuntu: `sudo apt-get install -y bats` · macOS: `brew install bats-core` · or `npm install -g bats` |

The repo's own CI installs these in [tests/common/build.sh](tests/common/build.sh)
(`npm install -g @devcontainers/cli`) before running `devcontainer up`.

## Production follow-ups (not blocking a test app)

* Pin the MDV image to a specific tag/digest instead of `:stable`.
* Provide `FLASK_SECRET_KEY` and DB credentials as real secrets (not committed defaults).
* Confirm `MDV_API_ROOT` if Workbench serves the app under a subpath.
* For durable data, move to a retained persistent disk (Option B) and add scheduled backups
  to a bucket (Option C) — see the advisory's persistence section.
* MDV is **GPL-3.0**; flag licensing to the enterprise customer.
