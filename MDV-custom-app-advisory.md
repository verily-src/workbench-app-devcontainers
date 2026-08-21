# MDV as a Verily Workbench Custom App — Advisory

Prepared for: Oxford IMCM (enterprise Verily Workbench customer)
Source project: [Taylor-CCB-Group/MDV](https://github.com/Taylor-CCB-Group/MDV) (Multi-Dimensional Viewer)

## What MDV actually is (and why it needs special handling)

MDV is **not a single-container app** — that is the crucial fact for a Workbench custom app.
From its `Dockerfile` and compose files, a working deployment is:

| Service | Role | Port | Notes |
|--------|------|------|-------|
| `mdv_app` | Flask + gunicorn (gevent) backend serving the built React frontend | **5055** | Runs as non-root user `pn`, `WORKDIR /app`, entrypoint via `uv run gunicorn ... mdvtools.dbutils.safe_mdv_app:app` |
| `mdv_db` | **PostgreSQL 16** — required, stores project metadata | 5432 | App connects via `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` |
| `mdv_pgadmin` | pgAdmin (optional, dev convenience) | 5054 | Not needed in Workbench |
| (optional) Redis | Only for multi-worker gunicorn (`-w >1`) | 6379 | Single worker does not need it |
| (optional) Ollama | Powers the "chat" LLM feature | 11434 | Only if they want ChatMDV |

Project data (Postgres + HDF5/`.h5` files) lives under `/app/mdv` (mapped from `~/mdv`).
Minimum 4 GB RAM; more for large datasets.

## The core challenge

The Workbench custom-app model (see the repo `README.md` and `src/example/docker-compose.yaml`)
assumes **one primary service** named `application-server`, on the external `app-network`, with
fuse capabilities and a `post-startup.sh` hook. MDV needs **two coupled services** (app +
Postgres). So this is a multi-service adaptation, not a plain `create-custom-app.sh` run.

## Multi-service precedent in this repo

This pattern is already established here, so we are not breaking new ground:

| App | Services | Relevance |
|-----|----------|-----------|
| **`src/playground`** | `app` (Caddy proxy = `application-server`) + `playground` (built) + **`db` (Postgres 18)** | **Best match** — web front + Postgres backend, same shape as MDV |
| `src/aou-sas` | `app` + `wondershaper` sidecar + `include:`d `secret-receiver` / `load-envs` | Multi-service via sidecars |
| `src/*-aou` (jupyter, nemo, r-analysis, parabricks) | `app` + `wondershaper` | Sidecar pattern |

Note: the `feature/applegath/vllm` branch (`src/vllm`) is **not** a multi-service example — it runs
code-server and Ollama as two processes inside a *single* `app` container (ports 8443 + 11434).

Key rules to copy from `src/playground/docker-compose.yaml`:

- **Only** the user-facing service is named `application-server` and joins the external
  `app-network`.
- The **Postgres service sits on a private internal network**, with no host port exposed — reachable
  by the app, invisible to Workbench and the outside.
- The app gates startup on a DB **healthcheck** via `depends_on: { condition: service_healthy }`.

## Recommended approach

**Use MDV's prebuilt stable image** (`mdvadmin/mdv:stable`, from `docker-local.yml`) rather than
building from the Dockerfile. Building requires the full MDV source in the build context and a
long pnpm + uv build; the published image is far faster and reproducible. For an enterprise
deployment, pin a **specific version tag / digest** (e.g. `v1.3.0`) instead of `:stable`.

The `src/mdv/` app would contain a `docker-compose.yaml` roughly like:

```yaml
services:
  app:                                   # the Workbench-facing service
    container_name: "application-server" # REQUIRED name
    image: "mdvadmin/mdv:stable"         # pin a digest for prod
    restart: always
    volumes:
      - .:/workspace:cached
      - mdv-data:/app/mdv                # persist projects + h5 files
    ports:
      - 5055:5055                        # MDV's port
    environment:
      - FLASK_ENV=production
      - DB_HOST=mdv_db
      - DB_USER=...        # via secrets, not hardcoded
      - DB_PASSWORD=...
      - DB_NAME=mdv_db
      - FLASK_SECRET_KEY=...
      - MDV_API_ROOT=/
      - ENABLE_AUTH=0      # see auth note below
    networks:
      - app-network      # Workbench-facing
      - mdv-internal     # to reach the DB
    cap_add: [SYS_ADMIN]
    devices: ["/dev/fuse"]
    security_opt: ["apparmor:unconfined"]
    depends_on:
      mdv_db:
        condition: service_healthy

  mdv_db:
    image: postgres:16
    restart: always
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ...
      POSTGRES_PASSWORD: ...
      POSTGRES_DB: mdv_db
    networks:
      - mdv-internal     # private only; NOT on app-network, no host port
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

volumes:
  mdv-data:
  postgres-data:

networks:
  # external network created by Workbench; only the app-facing service joins it
  app-network:
    external: true
  # private network for app <-> db traffic
  mdv-internal:
```

Plus a `.devcontainer.json` with `service: app`, the `post-startup.sh` / `remount-on-restart.sh`
hooks, and `remoteUser: root`.

## Decisions the customer (Oxford IMCM) needs to make

These materially affect the config, so confirm before building:

1. **Authentication** — *Resolved (customer meeting):* no in-app auth required; access is
   gated by Workbench, so MDV runs with `ENABLE_AUTH=0`. (Auth0 / Shibboleth remain available if
   they later want per-user login *inside* MDV, but that would require DB migrations and IdP
   config.)
2. **Data persistence** — named Docker volume (simple, tied to the VM) vs. a mounted Workbench
   cloud bucket under the user's home (survives VM recreation, shareable). For real research data,
   lean toward a bucket.
3. **Container user / home dir** — MDV's image runs as `pn`, not the usual `jovyan` / `root`.
   Workbench mounts buckets/repos under `${homedir}`, so confirm `pn`'s home and how that interacts
   with MDV's `/app/mdv` data dir.
4. **ChatMDV / LLM** — do they want the Ollama-backed chat feature? If yes, that is a third service
   and a GPU/CPU sizing conversation.
5. **Build vs. prebuilt image** — prebuilt is the recommendation; confirm they do not need local
   source modifications.
6. **Licensing** — MDV is **GPL-3.0**. Worth flagging to the enterprise customer since they are
   deploying it.
7. **Resources** — VM sizing for their expected dataset sizes (spatial datasets get large).

## Suggested next step

Scaffold a working `src/mdv/` app: start from `create-custom-app.sh` for port 5055, then adapt it
into the two-service app + Postgres layout above, wired with secrets rather than hardcoded
credentials.

To proceed, confirm:
- Auth approach: **none** / **Auth0** / **Shibboleth**
- Persistence: **named volume** / **cloud bucket**

## Persistence — detail

### MDV persists data in two separate places that must stay in sync

1. **PostgreSQL** — relational metadata: project records, users, and crucially the **filesystem
   path** to each project (`project.path`, e.g. `/app/mdv/42`). Lives in the DB data dir
   (`/var/lib/postgresql/data`).
2. **Project files on disk** — the actual datasets. Each project is a *directory* under
   `projects_base_dir` (default `/app/mdv`) containing HDF5 (`.h5`) binaries + JSON state. This is
   the bulk of the bytes.

The DB rows point at the on-disk directories. If the two drift apart (a DB row with no files, or
files with no row), MDV breaks. So **both stores must persist together** — you cannot keep one and
lose the other.

### Why "just put it in a Workbench bucket" isn't straightforward

Workbench mounts cloud buckets via **gcsfuse** (object storage presented as a filesystem). Great
for datasets you read; wrong for the semantics a database and live editing need:

- **Postgres on gcsfuse → corruption.** No POSIX file locking, no reliable `fsync`, no true
  random/partial writes. Postgres will refuse to start or corrupt its data dir. The DB data
  directory **cannot** live on a bucket.
- **MDV `.h5` files on gcsfuse → fragile for writes.** MDV memory-maps and does partial/random
  writes to `.h5` when adding data sources or editing annotations. gcsfuse rewrites whole objects
  with weak write consistency, so live editing is slow and can lose updates. Reads of static
  projects are fine; active editing is not.

So a pure-bucket deployment is not viable for live data. Buckets are for **input datasets** and
**backups/exports**, not the running DB or live project store.

### The realistic options

**Option A — Local named Docker volumes (default, simplest)**
- Both `postgres-data` and `mdv-data` on the VM's persistent disk.
- Correct semantics, fast, both stores stay consistent.
- Survives container restarts and VM stop/start. **Lost if the app/VM is deleted.**
- Not shareable between users or instances.

**Option B — Dedicated persistent disk (durable middle ground)**
- Same as A, but volumes sit on a separately-provisioned persistent disk retained across VM
  recreation.
- Real block-storage semantics (DB is happy) plus durability beyond the VM lifecycle.
- Best fit for "must not lose data" — confirm what Workbench supports for attaching/retaining a PD.

**Option C — Local live data + scheduled backup to a bucket (recommended for production)**
- Run live on A or B for correctness/speed.
- Periodically snapshot **both** stores together to a bucket: `pg_dump` **and** a tar / `gsutil
  rsync` of `/app/mdv`, taken as one consistent snapshot. MDV can also export projects as
  self-contained directories, which makes portable, bucket-friendly backups.
- Delivers the durability/shareability people want from a bucket without asking gcsfuse to do
  things it can't.

### Bottom line

- Live data (Postgres + `/app/mdv`) → **local volumes** (A), upgraded to a **retained persistent
  disk** (B) if the data must outlive the VM.
- **Buckets** → for **ingesting source datasets** (read-mostly) and **holding backups/exports** (C),
  not for the running DB or live project store.
- Two questions for the customer: (1) must data survive VM/app deletion? (→ B); (2) do multiple
  people/instances need to share the same projects? (→ a shared MDV instance or export/import via
  bucket, not a shared live mount).

## Institutional SSO (Shibboleth) — how realistic inside a Workbench app?

Short version: **within a per-user Workbench custom app, native Shibboleth is not realistic — and
largely redundant.**

### What MDV's Shibboleth mode actually requires

MDV does not speak SAML itself. Its `shibboleth` mode (`SHIBBOLETH_LOGIN_URL` /
`SHIBBOLETH_LOGOUT_URL` in `docker-secrets.yml`) **trusts HTTP headers** (e.g. `eppn`, `mail`)
injected by a **Shibboleth Service Provider (SP)** running in front of it — Apache + `mod_shib` (or
an nginx equivalent) plus the `shibd` daemon. MDV only reads the resulting headers.

### Why that doesn't fit a per-user Workbench app

1. **No stable, registrable callback/ACS URL.** SAML redirects the browser to Oxford's IdP and back
   to the SP's Assertion Consumer Service endpoint, which must be a fixed public HTTPS hostname
   **registered in the IdP metadata**. A Workbench app runs on a per-user VM behind Workbench's own
   proxy — there is no stable per-instance hostname to register. Per-user SP registrations or a
   wildcard are impractical.
2. **SP registration is an institutional action.** Oxford's IdP is in the UK Access Management
   Federation. Onboarding an SP means entityID, certificate exchange, metadata, and IT Services
   approval — a one-time institutional process, not a per-instance step.
3. **Extra in-container machinery.** You would add `shibd` + a web-server SP module as another
   service layer purely to synthesize the headers MDV consumes. More moving parts, more failure
   modes.
4. **It's redundant.** Workbench already authenticates the user before the request reaches the app,
   and the app is single-user. A second institutional login adds little, while the header-trust
   model is fragile behind a proxy chain (identity headers must be guaranteed unspoofable).

### Where SSO *is* realistic

- **A shared, self-hosted MDV outside Workbench** (dedicated VM/service with a stable hostname).
  There, one SP registration + MDV's `SharedObject` multi-user model is exactly what Shibboleth mode
  is designed for. This is the "shared lab portal" deployment, not the per-user sandbox.
- **Auth0 with a SAML/OIDC enterprise connection federating to Oxford SSO** is the more tractable
  middle ground *if* in-app identity is ever needed: Auth0 handles the SAML dance and hands MDV OIDC
  (`AUTH0_*` settings), so you register **one** app/tenant instead of a federation SP. It still needs
  a **stable callback URL** (`AUTH0_CALLBACK_URL`) the app is reachable at, so it only becomes
  feasible if Workbench exposes a stable per-app URL that survives the OIDC redirect round-trip
  (confirm with the Workbench platform team). Raw Shibboleth SP-in-container remains impractical
  either way.

### Recommendation

Rely on Workbench for access control (`ENABLE_AUTH=0`) for the Workbench app. If Oxford genuinely
needs institutional SSO plus in-app multi-user sharing, treat that as a **separate shared MDV
deployment**, and prefer **Auth0-federated OIDC** over native Shibboleth if/when they want it —
reserving raw Shibboleth for a properly-hosted shared instance.
