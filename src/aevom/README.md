# Aevom (NVIDIA agent for life sciences)

Code-server IDE with [Aevom](https://github.com/NVIDIA-BioNeMo/agent-for-lifesciences),
NVIDIA's agentic molecular-science harness: a chat UI with a Molstar 3D viewer
in front of a LangGraph agent that drives RDKit, AutoDock Vina, ADMET-AI, PLIP
and the BioNeMo NIM skills (OpenFold3, Boltz-2, RFdiffusion, ...). Everything is
built on the VM from the pinned upstream commit `2549b68` (initial public
release); no prebuilt images are needed.

- Code-server UI on port 8443, with the Workbench CLI, bucket mounts and a terminal.
- Aevom UI at `<app URL>/proxy/8000/` (code-server's port proxy); API docs at `.../proxy/8000/docs`.
- Tool services, Postgres, Redis and Phoenix share the app container's network
  namespace and are reachable only on `localhost` inside the app.

Use **`src/aevom`** as the template path when creating this app.

> Aevom is research-grade software with no user authentication of its own, and
> it executes model-generated Python (in the upstream `pyexec` service with
> RestrictedPython). It is reachable only through Workbench sign-in to this app.
> Read upstream's [SECURITY.md](https://github.com/NVIDIA-BioNeMo/agent-for-lifesciences/blob/main/SECURITY.md).

## Prerequisites

| Requirement | Notes |
|---|---|
| NVIDIA API key | From [build.nvidia.com](https://build.nvidia.com/). Needed by the default model `nemotron-3-5-super-vl` and by the NIM-backed tools. |
| VM | 8 vCPU / 32 GB (for example `n2-standard-8`) and a 200 GB boot disk. No GPU needed: Vina runs on the CPU. |
| First start | 30-45 minutes, dominated by compiling RDKit from source. Later starts reuse the cached images. |

Anthropic and OpenAI keys are optional and add those vendors' models to the
model dropdown (see upstream's "Model Selection").

## Usage

1. Open the app (code-server) and a terminal.
2. Store your NVIDIA API key. It is prompted for and not echoed:

   ```sh
   aevom key nv
   ```

   The Aevom API waits for the first key before it starts, then picks up new
   or changed keys on the next request. `aevom key anthropic` and
   `aevom key openai` add the optional providers.
3. Check the stack:

   ```sh
   aevom status
   ```

   All services should report `200`. ADMET-AI takes a minute or two to load
   its ensembles after start.
4. Open the Aevom UI: in the browser address bar, append `proxy/8000/` to this
   app's URL so it ends in `.../proxy/8443/proxy/8000/`. `aevom url` prints
   the same instruction.

Keys are stored in `~/.aevom/` on the persistent `/config` volume, so they
survive restarts. Everything Aevom produces (molecules, structures, docking
results) lives in its Postgres volume and is downloadable from the UI's storage
panel; save anything you want to keep to a workspace bucket under
`~/workspace`.

## How it works

| Compose service | Role | Port (localhost) |
|---|---|---|
| `app` (`application-server`) | Code-server, wb CLI, bucket mounts, the `aevom` helper | 8443 (published) |
| `aevom-api` | FastAPI backend serving the React UI; built by `aevom-api.Dockerfile` | 8000 |
| `aevom-rdkit` | SMILES handling, depiction, SAFE | 8001 |
| `aevom-pyexec` | Sandboxed Python for `python_execute` (RestrictedPython) | 8002 |
| `aevom-vina` | Receptor/ligand prep and AutoDock Vina docking (CPU) | 8003 |
| `aevom-admet` | ADMET-AI predictions | 8004 |
| `aevom-plip` | Protein-ligand interaction profiling | 8005 |
| `aevom-postgres` | Artifact store | 5432 |
| `aevom-redis` | Session state | 6379 |
| `aevom-phoenix` | Trace collector | 4317 (UI on 6006) |

The tool services build straight from the upstream repository using git-URL
build contexts, with their Dockerfiles unchanged. Upstream runs each on port
8000 behind compose DNS; here they share one network namespace
(`network_mode: service:app`), so each gets its own port via `command` and the
API's `*_SERVICE_URL` variables.

### Changes relative to upstream

- **`workbench.patch`** (frontend only, 4 files). Workbench and code-server both
  serve the app under a path prefix that they strip before forwarding. The
  upstream frontend assumes it is served from `/`, so the patch sets Vite's
  `base` to `./` and adds `workbenchProxyShim.ts`, which rewrites root-relative
  `/api/...` URLs passed to `fetch()` and `EventSource` to be relative to the
  page. `aevom-api.Dockerfile` applies it with `git apply` after cloning, so a
  version bump that changes those lines fails the build rather than shipping an
  unpatched UI.
- **API keys** come from `~/.aevom` instead of files in the checkout. The
  `aevom-api` image symlinks Aevom's fixed `/run/secrets/*` paths to that
  volume and waits for the first key (`aevom-api-entrypoint.sh`).
- **`PYEXEC_MODE=direct`**: `python_execute` uses the shared `pyexec` service.
  Upstream's default OpenShell sandbox needs the host Docker socket and is not
  used here.
- **CPU Vina**: Workbench attaches GPUs to the `app` service only, so the
  Uni-Dock GPU build is not used.
- The `molstar-headless` service is omitted: nothing in the API or UI calls it.

### Configuration

The model and feature flags are environment variables on `aevom-api` in
`docker-compose.yaml` (Workbench substitutes only a fixed set of template
options, so they are not template options). To change the default model, edit
`AEVOM_MODEL` in your fork and point the app at that branch. To upgrade Aevom,
change the commit in `aevom-api.Dockerfile` (`AEVOM_COMMIT`) and in the five
git-URL build contexts in `docker-compose.yaml`, then check that
`workbench.patch` still applies.

## Debugging

From the code-server terminal:

```sh
aevom status                 # health of every service and the model list
aevom keys                   # which providers have a key
curl -s localhost:8000/api/info | python3 -m json.tool
```

Container logs are not visible from inside the app. From the VM (SSH):

```sh
docker ps
docker logs $(docker ps -qf name=aevom-api) --tail 100
sudo journalctl -u devcontainer.service --no-pager | tail -100
```

If `aevom-api` logs `waiting for an LLM API key`, run `aevom key nv` in the
app. If the first build fails on `aevom-rdkit`, the VM is usually short of
memory or disk for the RDKit compile; use a larger VM and a 200 GB disk.
