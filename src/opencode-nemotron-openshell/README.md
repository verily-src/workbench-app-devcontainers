# OpenCode + NVIDIA Nemotron in NVIDIA OpenShell

Code-server IDE with [OpenCode](https://opencode.ai) running in an
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, on local
[NVIDIA Nemotron](https://developer.nvidia.com/topics/ai/nemotron) models served by
[Ollama](https://ollama.com). Based on `src/opencode-nemotron-mcp`; the model
setup is the same. The default is **Lightning 30B on A100/H100**, or
**experimental Nano 4B on T4/V100**.

The premise: people are trusted more than agents. You keep your Workbench
credentials and tools in code-server. The agent runs in a sandbox that holds no
credentials and, by default, can reach nothing but the local models. Every
connection it attempts is checked against a policy you can edit, and logged.

- Code-server UI on port 8443. A temporary firewall rule, `port-guard`, closes it to other VMs (see [Limits](#limits)); it is not part of the agent's isolation.
- `opencode` starts OpenCode in the sandbox; `agent-sandbox` manages it and runs any other [harness](#harness).
- Ollama API on `127.0.0.1:11434` inside the container, also published on the
  VM's loopback for the sandbox.
- OpenShell 0.1.4 gateway in its own container, with telemetry off.

Use **`src/opencode-nemotron-openshell`** as the template path when creating this app.

## How it works

```
code-server (you: Workbench credentials, wb, gcloud, Claude Code)
  └─ opencode ──▶ OpenShell gateway container (holds the Docker socket)
                    └─ creates ──▶ sandbox container: OpenCode, non-root, no credentials
                                     │ every connection checked by the OpenShell supervisor
                                     ├─ allowed: Ollama chat API (local Nemotron)
                                     └─ denied and logged: everything else
```

| Container | Role |
|---|---|
| `application-server` | Code-server, Ollama on the GPU, the `openshell` CLI. No Docker socket |
| `openshell-gateway` | OpenShell control plane. Holds the VM's Docker socket and creates sandboxes. Reachable only from this VM |
| `openshell-init` | Generates the gateway's keys, then exits |
| `sandbox-image` | Builds the sandbox image `opencode-agent-sandbox:0.2`, then exits |
| `port-guard` | Outside the framework, and temporary. Protects *your* code-server, not the agent's sandbox: it drops connections to port 8443 from other VMs, so code-server is reachable only through Workbench sign-in. Re-applies its rule every minute and writes its status to `/opt/port-guard/port-guard` in the app |
| Sandbox (created on first `opencode`) | The harness (OpenCode by default) and anything it runs. User `sandbox` (uid 1500); only `/sandbox` and `/tmp` are writable |

The sandbox reaches Ollama as `host.openshell.internal:11434`, which OpenShell's
Docker driver maps to the VM's loopback. The default policy allows only
`POST /v1/chat/completions` and `GET /v1/models` there, so Ollama's `/api/pull`
and `/api/push`, which reach model registries on the internet, stay blocked.

## Models and GPU guidance

At startup the app detects the largest attached GPU's VRAM and filters the
catalog in `models.json`. Every compatible catalog model is downloaded so it is
usable from OpenCode's `/model` picker. On first start, each model is loaded
sequentially and must pass a full-GPU, configured-context check before startup
publishes the configuration. Only one model is kept in VRAM at a time, with the
default loaded last. Later restarts check only the selected model; see
[Startup checks](#startup-checks).

| Ollama tag | Weight download | Minimum VRAM | Available on |
|---|---|---|---|
| `nemotron-3-nano:4b` (experimental) | 2.8 GB | 15,000 MiB | T4/V100 16 GB and larger GPUs |
| `nemotron-3.5-lightning:30b` | 25 GB | 40,000 MiB | A100 40/80 GB and H100 80 GB variants |

On a T4/V100, `/model` offers Nano 4B only. On an A100/H100, it offers Nano 4B
and Lightning 30B. Capacity thresholds deliberately use MiB rather than GPU
names so provider-specific labels such as `MEGA` do not affect filtering.
Custom tags remain available through `opencode-model` for experimentation.
Nano 4B produced silent failures in 2 of 5 reported tests with the full Workbench
tool inventory. It remains available for experimentation, not as a reliability
claim. Lightning needs the same full-inventory evaluation on the target GPU.
Sizes and tool support come from the
[Nano tags](https://ollama.com/library/nemotron-3-nano/tags) and
[Lightning tag](https://ollama.com/library/nemotron-3.5-lightning:30b).
Example GCP configurations for the primary targets are N1 with one T4 and
`a2-highgpu-1g` with one A100 40 GB. See
[GCP GPU configurations](https://docs.cloud.google.com/compute/docs/gpus)
for memory capacities and machine availability.

**P4 8 GB is excluded from the catalog** at the configured 64K context. It leaves less
memory for context and runtime allocations. Ollama also requires
driver 570 or newer for P4; see
[Ollama hardware requirements](https://docs.ollama.com/gpu).

GPU suggestions are memory-budget estimates, not benchmark results. Weights are
only part of VRAM use: context, KV cache, and runtime allocations also need room.
Check `ollama ps` for `100% GPU` at the configured context length, and compare
task quality and latency on your target VM. Smaller models can be less reliable
on complex coding and MCP tasks. A T4 offers a smaller hardware configuration
than an A100; actual cost depends on region, machine size, and provisioning.

The older `nemotron-mini:4b` is deliberately excluded: its
[4K context window](https://ollama.com/library/nemotron-mini/tags) is too short
for OpenCode plus Workbench context and MCP tools.

## Usage

1. Open the code-server IDE and a terminal.
2. Check the sandbox once after the app's first start (about a minute):

   ```sh
   agent-sandbox selftest
   ```

   All checks should pass before you rely on the sandbox; see [Self-test](#self-test).
3. Copy a project into the sandbox and start the agent:

   ```sh
   agent-sandbox upload ~/repos/<your-repo>   # lands in /sandbox/work/<your-repo>
   opencode                                      # opens in /sandbox/work
   ```

4. Copy results back out:

   ```sh
   agent-sandbox download <your-repo>          # to ~/sandbox-downloads/
   ```

The sandbox has its own filesystem: it cannot see `/config`, your repos or bucket
mounts. Files in it persist until `agent-sandbox reset`, but download
anything you want to keep, and save it to a bucket.

The initial startup downloads every model compatible with the attached GPU,
validates each model on the GPU, and leaves the default loaded. Subsequent
restarts reuse cached weights in the model store (`/config/.ollama/models`
unless [moved to a bucket mount](#model-store-on-a-bucket-mount)); they do not
pull models again. To update an existing tag deliberately, run `ollama pull <tag>`.

## Sandboxed agent

The framework runs one agent program, the **harness**, in the sandbox. OpenCode is
the default; [another harness](#harness) is a config file. `agent-sandbox` manages
the sandbox (`agent-sandbox` is the same command under its phase 1 name).

### Commands

| Command | What it does |
|---|---|
| `opencode [args]` | Start the default harness (OpenCode) in the sandbox, creating the sandbox if needed |
| `agent-sandbox run [args]` | Start the active harness, whichever it is |
| `agent-sandbox harness [name]` | List the shipped harnesses, or make one active |
| `agent-sandbox shell` | A shell in the sandbox |
| `agent-sandbox upload <path> [dest]` / `download <path> [dest]` | Copy files in or out |
| `agent-sandbox status` | The gateway, the sandbox and the policy file |
| `agent-sandbox logs [count]` | Recent network decisions: program, destination, allowed or denied, and why |
| `agent-sandbox rules` | Rules OpenShell drafted from blocked connections, waiting for you |
| `agent-sandbox approve <chunk-id>` / `reject <chunk-id>` | Decide a drafted rule. Approval changes only this sandbox |
| `agent-sandbox policy` | Apply your edited policy, data-access and harness files to the running sandbox |
| `agent-sandbox reset --yes` | Delete the active harness's sandbox and its files, and create a new one |
| `agent-sandbox selftest` | Check isolation and model access |

Inside the sandbox the agent runs autonomously: you are asked only when it tries
to reach something outside the policy. OpenCode's config allows only the local
Ollama provider, has no MCP servers, disables sharing, updates and web fetches, and
tells the agent it is sandboxed (`sandbox-image/sandbox-instructions.md`).

### Harness

A harness is the agent program that runs in the sandbox. Everything the
framework needs to know about it is one file, `/config/openshell/harness.yaml`
(copied on first start from `openshell/harnesses/opencode.yaml`, which explains
each field):

| Field | Meaning |
|---|---|
| `name` | Names the sandbox, `agent-<name>`. Each harness has its own sandbox |
| `image` | Image the sandbox is created from |
| `binaries` | Real paths of the programs allowed to call Ollama's chat API. `render-policy.py` writes them into the policy's `local_models` rule |
| `command`, `workdir`, `env` | What to run, where, and its extra environment. Arguments to `agent-sandbox run` are appended to `command` |
| `config` (optional) | A hook that prints the harness's configuration in the app, and the variable the sandbox receives it in. For OpenCode, the JSON in `OPENCODE_CONFIG_CONTENT` |
| `selftest` (optional) | Arguments to run and a `grep -E` pattern the output must match |

Every harness gets two variables: `OLLAMA_BASE_URL` (Ollama's OpenAI-compatible
API, the only thing the default policy lets it reach) and `AGENT_MODEL`. The
framework alone decides what the sandbox may reach; a harness file can't widen
the policy, only name which programs use the model endpoint.

To try the second shipped harness, a 20-line Python script that sends one chat
request:

```sh
agent-sandbox harness chat-once
agent-sandbox reset --yes     # creates agent-chat-once
agent-sandbox run "Reply with exactly one word: ready"
agent-sandbox selftest        # the same isolation checks, run for this harness
```

To bring your own, copy one of the files, change it, and keep it as
`/config/openshell/harness.yaml`. The image must contain your program and its
dependencies; the framework builds only the OpenCode image. Networks and data
beyond the model need rules in `policy.yaml` or [Data access](#data-access), as
for any harness.

### Policy

The default policy is `openshell/policy.yaml`. On first start it is copied to
`/config/openshell/policy.yaml`, which persists across restarts and is yours to
edit. It is never overwritten; delete it to get the current default again.

- **Network rules** apply to the running sandbox within seconds:
  `agent-sandbox policy`. The file has a commented example.
- **Filesystem and process rules** apply only to a new sandbox:
  `agent-sandbox reset --yes`.
- When the agent is blocked, OpenShell drafts a narrow rule (one program, one
  host). `agent-sandbox rules` lists them; approve only what you understand.
  Planted instructions in files or data can make an agent ask for exactly the
  wrong destination.

### Data access

Off by default. When on, the sandbox can query BigQuery and read Cloud Storage
buckets that you list, with restrictions the human user doesn't have. Edit
`/config/openshell/data-access.yaml` (copied from `openshell/data-access.yaml` on
first start), set `enabled: true` and list your project, datasets and buckets,
then run `agent-sandbox reset --yes` once (a credential provider attaches
only to a new sandbox). Later edits apply with `agent-sandbox policy`.

```yaml
enabled: true
project_id: my-workspace-project
bigquery:
  datasets:
    - {project: my-workspace-project, dataset: synthetic_allofus}
storage:
  buckets: [synthetic-allofus-poc-my-workspace-project]
```

Everything here is OpenShell configuration; there is no gate service or
middleware. `render-policy.py` adds two rules to `policy.yaml` and writes the
result to `/config/openshell/policy.effective.yaml`, the file the sandbox runs
with. `policy.yaml` stays as you wrote it.

| Restriction | How |
|---|---|
| No Google credential in the sandbox | The `google-cloud` provider (`wb-gcp`) is created from this app's Application Default Credentials. The refresh token stays at the gateway; the sandbox sees a placeholder, and the proxy swaps in the real token only on requests a rule allows. |
| Cloud Storage is read-only, even where you can write | `GET` only, on the listed buckets. Uploads and deletes are denied. |
| No BigQuery changes through the API | Only query jobs run (`POST` to `jobs` and `queries`, in your project). `DELETE`, `PATCH`, `PUT`, `insertAll` and uploads are not listed, so they are denied. |
| BigQuery scope | Table and dataset lookups only in the listed datasets; jobs only in your project; no dataset listing. |
| Only the Python client reaches Google | The rules name one interpreter (`/usr/bin/python3.11`; venvs resolve to it). `curl` is blocked. |

Workbench still applies first: the agent acts as you, so your IAM roles,
read-only settings and data collection policies bind it too.

**Known gap.** OpenShell rules see the method and path, not the request body. A
BigQuery `DELETE FROM` or `DROP TABLE` is a query job like any other, so it
passes. A SQL statement can also name any table you can read, in any project.
Rely on Workbench for both (read-only resources, IAM, data policies) and keep the
agent's identity narrow. Load jobs and the Storage Read API (gRPC,
`bigquerystorage.googleapis.com`) are not covered by a rule: the former can
write tables from a bucket the agent may read, the latter is blocked, so use
`create_bqstorage_client=False` when reading dataframes.

### Agents outside the framework

This app has no unsandboxed mode: `opencode` always starts the agent in the
sandbox. An agent you start yourself in code-server (Claude Code, a hand-run
OpenCode) runs with your own credentials and network, outside the framework.
That is your choice as the human; OpenShell doesn't see or restrict it.

### Self-test

`agent-sandbox selftest` checks, in the live sandbox, that:

- it runs as a non-root user and system folders are read-only;
- it holds no cloud credentials and no `gcloud`, `wb`, `bq` or `gsutil`;
- the public internet, the cloud metadata server, code-server and the OpenShell
  gateway are unreachable;
- Ollama's `/api/pull` and `/api/tags` are refused, and its chat endpoint answers;
- OpenCode in the sandbox completes a call to the local model;
- OpenShell logged the blocked internet request;
- the gateway's audit JSONL is being written (skipped if the folder is not mounted);
- port-guard reports its rule in place within the last 5 minutes (a check on your code-server's exposure, not on the sandbox);
- with data access on: the Google token is a placeholder, a BigQuery query runs,
  and table deletes, `insertAll`, dataset browsing, queries billed to another
  project, `curl` to BigQuery, bucket writes and unlisted buckets are all denied.

The app can't test its own network card, so the self-test ends with a `curl`
command to run from another app in the workspace: it should time out, not
return HTTP 302. `agent-sandbox status` shows port-guard's full status.

### Audit log

OpenShell logs every network decision the sandbox makes, allowed and denied,
with the program, the destination, the policy rule and the reason. It does not
log commands or file activity inside the sandbox; OpenCode's own session log
covers that, in the sandbox under `/sandbox/.local/share/opencode`.
`agent-sandbox logs` shows the recent decisions.

What is kept, where, and what is not (OpenShell 0.1.4, Docker driver):

| Record | Where | Lifetime |
|---|---|---|
| The sandbox's decisions (connections, requests, policy and rule changes) | The gateway, in memory: the last 2,000 lines per sandbox | Lost when the sandbox is deleted or the gateway restarts. `agent-sandbox audit save` and `reset` copy them to `/config/openshell/audit/` first |
| Gateway events: sandbox created or deleted, policy updated, rule approved | `/var/lib/openshell/audit/gateway-ocsf.jsonl` on the VM (OCSF JSONL, daily rotation, 30 files; `[openshell.gateway.ocsf_log]` in `gateway.toml`) | Survives sandbox resets. Lost if the app is deleted |
| OpenShell's full JSON records of the sandbox's decisions (`ocsf_json_enabled`, which the wrapper turns on) | The supervisor container's stderr and tmpfs, on the VM | Not reachable from the app or the agent. Keeping them needs a collector on the VM that reads the supervisor container's Docker logs. This framework has none |

So the durable, complete record of what the agent was allowed and denied is not
available from inside the app, and the gateway's JSONL does not contain it. What
you can keep from the app is the 2,000-line snapshot of the sandbox's decisions
and the gateway's JSONL of control-plane events.

```sh
agent-sandbox audit save                          # to /config/openshell/audit/
agent-sandbox audit export gs://my-bucket/audit   # save, then copy to a bucket
```

`audit export` is a command you run; nothing runs in the background. Exporting
before you stop or delete the app keeps the record outside the VM.

The agent can't change any of this. The supervisor's files are in its own
container, the gateway's file is on the host, and neither is mounted in the
sandbox (`/var/log` there is read-only). OpenShell documents all of these
sources as best-effort collection, not a guaranteed complete audit history:
queues are bounded and drop records under load.

### Limits

- **The gateway holds the VM's Docker socket,** which is root on the VM in
  effect. It is in its own container and reachable only from this VM, but it is
  unauthenticated there: anything on this VM's `app-network` can drive it.
- **Ollama has no authentication** and listens on all interfaces inside the
  container, so other containers on this VM's `app-network` can reach it. It is
  not reachable from other VMs.
- **No Workbench MCP tools in the sandbox.** BigQuery and Cloud Storage are
  reachable through [Data access](#data-access), with the gap described there.
- **OpenCode tries to install its plugin package from npm on start.** The
  sandbox blocks it, OpenCode works without it, and the attempt appears in
  the log as denied.
- **port-guard is outside the framework, and temporary.** OpenShell already
  refuses port 8443 from the sandbox. port-guard protects your code-server from
  other VMs in the network, a Workbench-level exposure that likely affects every
  code-server app and should be fixed in the platform (the proxy agent connecting
  without a published port, or a VM firewall rule). It is a host firewall rule
  set from a container; on the first test app it didn't take effect and
  code-server was reachable from other VMs. Check it from another VM after every
  new deployment.
- **The audit trail is partial.** See [Audit log](#audit-log): the sandbox's
  decisions are kept only as a 2,000-line snapshot, and the full JSON records
  need a collector on the VM.
- OpenShell is version 0.x; expect changes.

## Model selection

### Choose or change a model

Inside OpenCode, use `/model` to switch among the models that fit the attached
GPU. Ollama loads the selection and evicts the previous model when necessary;
switch latency depends on the model and storage, but the models do not need to fit in
VRAM concurrently.
Only the Ollama provider is enabled. No separate background `small_model` is
configured, so title generation can use the current Nemotron selection.

The companion command changes the persisted default or selects a custom tag:

```sh
opencode-model                         # numbered menu, including GPU guidance
opencode-model --list                  # inspect choices without downloading
opencode-model nemotron-3-nano:4b       # noninteractive selection
```

The command lists only catalog models compatible with the attached GPU. It
downloads all compatible choices, checks Ollama's advertised tool support and
GPU residency at the configured context, then updates both `/config/.opencode-model` and the
OpenCode config. Start a new OpenCode session after changing the persisted
default. A download or loading failure leaves the saved selection and OpenCode
config unchanged. Previously downloaded models stay cached; use
`ollama rm <tag>` to reclaim their disk space. Do not run `ollama rm` against a
store that other apps share.

The existing override workflow also works:

```sh
echo nemotron-3-nano:4b > /config/.opencode-model
# Restart the app to apply this manually written override.
```

The saved tag survives restarts and machine-type changes. Select a smaller model
before moving from an A100 to a T4/V100. Delete `/config/.opencode-model` and restart
to return to the compose default. Custom Ollama tags can be passed to the picker;
they must support tools, sufficient context, and your GPU. The catalog uses local
model tags, not Ollama cloud models.

### Optional first-launch prompt

Set this in your fork's `docker-compose.yaml` before creating/rebuilding the app:

```yaml
OLLAMA_MODEL: "prompt"
```

Startup launches the services without downloading a model. On the first
interactive `opencode` launch, a terminal menu asks for a default model, then
downloads and validates all compatible choices. Later launches use the saved choice. An existing
`/config/.opencode-model` takes precedence, so remove it to try the prompt on an
existing app. Cancelling the menu leaves the selection unset.

For automation, run `opencode-model <tag>` first. A model-dependent command
without a terminal fails with instructions rather than waiting for input.
Help and version remain available.

The optional prompt implements initial selection at the first agent launch because devcontainer
`postCreateCommand`/`postStartCommand` run without an interactive terminal.
Blocking those hooks on `read` would prevent startup. Other options considered:

- **Workbench creation-form selection:** would require platform changes.
  Workbench substitutes a fixed set of template options on the VM, so adding
  a `model` template option here alone does not work.

## Workbench tools for you, not the agent

This app still installs the `wb-mcp-server` and `llm-context` features from the
Jupyter LLM template, for Claude Code and other tools you run yourself in
code-server. After Workbench authentication and mounts, `start-services.sh`:

1. Starts the feature's HTTP MCP daemon as `abc`.
2. Generates Workbench context as `abc` once the workspace is available.
3. Starts Ollama as `abc`, checks its pinned version, and validates the models
   (or defers selection); see [Startup checks](#startup-checks).

The sandboxed agent gets none of this: no Workbench MCP tools, no `wb` login, no
Workbench context files. It reaches data only through the rules in
[Data access](#data-access).

```sh
wb workspace describe
generate-llm-context   # refresh after authentication or workspace changes
```

## Configuration

`resolve-model.sh` applies this precedence: `/config/.opencode-model`, then
`OLLAMA_MODEL`, then `auto`. Auto chooses the highest-priority compatible catalog
model: Lightning on A100/H100, Nano 4B on T4/V100. Both the agent config and
Ollama startup use it. A saved choice from an earlier version is retained.

`available-models.sh` reads the largest attached GPU's memory with `nvidia-smi`
and filters `models.json` by `minimum_vram_mib`. `OPENCODE_GPU_MEMORY_MIB` can
override detection for testing or an operator-controlled deployment.

The sandbox's OpenCode configuration is built at launch by the harness config hook (`openshell/harnesses/opencode-config.sh`).
It registers every compatible catalog model so OpenCode's `/model` picker cannot
accidentally select a catalog model that is too large for the GPU. This is a
usability guard, not a security boundary; users can still supply a custom Ollama
tag. It also pins `autoupdate: false`, disables sharing, enables only Ollama, and
registers no MCP servers.

OpenCode is pinned to 1.18.22. `ollama-release.json` pins Ollama 0.34.4 and the
SHA-256 of its Linux amd64 release archive. The build verifies that checksum;
startup rejects an already-running server with a different version. A100/H100
need a compatible NVIDIA host driver (550+ for this Ollama release). Model tags
remain mutable; the GPU acceptance report records the digests actually tested.

`OLLAMA_CONTEXT_LENGTH` defaults to 65536, following
[Ollama's OpenCode guidance](https://docs.ollama.com/integrations/opencode).
The same limit is advertised to OpenCode so its context management matches the
server. Larger contexts consume more VRAM. `OLLAMA_NUM_PARALLEL=1` and
`OLLAMA_MAX_LOADED_MODELS=1` limit concurrent model memory use. Switching models
still evicts the previous one. `OLLAMA_KEEP_ALIVE=-1` keeps the active model
loaded, however long it is idle, until a switch or an Ollama restart. An
unloaded model is reloaded by the next request, and OpenCode waits for it. On an
`a2-highgpu-1g`, a cold Lightning reload took about 3 minutes from a bucket
mount and 11–12 minutes from the local disk. The model keeps its VRAM while
idle; the GPU is dedicated to this app. The startup check uses the same keep-alive.
`OPENCODE_HOME` defaults to `/config` and can redirect state for script testing.

### Startup checks

`start-services.sh` runs on every app start. It publishes the OpenCode
configuration only if `start-ollama.sh` succeeds. Its checks depend on the
situation:

| Situation | Models loaded and checked |
|---|---|
| First start; a model was downloaded; the compatible model set, model store, or context length changed; or the previous check failed | Every compatible model, one at a time, selected model last |
| `opencode-model` selection | Every compatible model, one at a time, selected model last |
| Any other restart | Only the selected model |

The result of the last successful check is recorded in
`/config/.ollama/validated-models.json`. Delete it to force a full check on the
next start.

Each restart starts with a cold page cache, so every check reads the model from
storage. On an `a2-highgpu-1g`, a cold load of a 25 GB model file from the
local persistent disk took about 13 minutes. That is longer than
Ollama's default five-minute load limit, so `OLLAMA_LOAD_TIMEOUT` is set to
`20m`. `validate-model.sh` waits up to 25 minutes, longer than that limit. If you
raise `OLLAMA_LOAD_TIMEOUT`, keep it below 25 minutes. From a
[bucket mount](#model-store-on-a-bucket-mount), the Lightning 30B startup check
passed in about 2.7 minutes on the same VM.

Every `OLLAMA_*` setting in `docker-compose.yaml` must also be listed in
`--preserve-env` in `start-services.sh`; otherwise it does not reach `ollama serve`.

### Model store on a bucket mount

On VM types with slow local disks, keeping the Ollama model store on a
Workbench bucket mount makes cold loads several times faster: 3.4–5.8 times in
tests on an `a2-highgpu-1g`. Inference speed is
the same in both cases, because the weights are in VRAM once loaded. A store on
a bucket can also be shared by several apps, and new apps do not need to
download from the registry.

**New apps find a store on their own.** At startup, if no store is set,
`find-model-store.sh` looks through the workspace's bucket mounts, at
`/config/workspace/<bucket-resource>` and one folder below it, for an Ollama
store (`blobs/` and `manifests/`) that already holds every model this GPU needs.
The first match, in name order, is used, and startup logs which one. If no
store holds every model, the app uses `/config/.ollama/models` and downloads
from the registry as before. A store missing a model is never chosen
automatically, so the app doesn't write new downloads into a shared bucket you
didn't pick.

To pin a store, or use one deeper in a bucket, write its mounted path to
`/config/.opencode-model-store` and restart the app:

```sh
echo /config/workspace/<bucket-resource>/ollama-store > /config/.opencode-model-store
```

The file takes precedence over the search and over `OLLAMA_MODELS`. Startup
fails with a clear message if the path is not an existing directory, for
example when the bucket is not mounted. Delete the file and restart to return to
automatic selection. Set `OPENCODE_MODEL_STORE_SEARCH=off` in
`docker-compose.yaml` to turn the search off, or to a directory to search there
instead of `/config/workspace`.

Populate the store once, from an app that has already pulled the models.
Copy straight to the bucket with `gcloud storage`, not through the mount; it is
faster and avoids partial files. For each model, copy:

- `manifests/registry.ollama.ai/library/<model>/<tag>`
- every `blobs/sha256-*` file the manifest references (its `config` and `layers` digests)
- `metadata/sha256-<weights layer digest>.json`, if present

```sh
store=gs://<bucket>/ollama-store
manifest=registry.ollama.ai/library/nemotron-3.5-lightning/30b
cd /config/.ollama/models
gcloud storage cp "manifests/${manifest}" "${store}/manifests/${manifest}"
for digest in $(jq -r '.config.digest, .layers[].digest' "manifests/${manifest}"); do
  gcloud storage cp "blobs/${digest/:/-}" "${store}/blobs/"
  if [[ -f "metadata/${digest/:/-}.json" ]]; then
    gcloud storage cp "metadata/${digest/:/-}.json" "${store}/metadata/"
  fi
done
```

Copy every model that is compatible with the target GPU (both catalog models on
an A100/H100); automatic selection needs all of them. With a pinned store, a
missing model is downloaded through the mount instead.
Use the registry builds that the app pulls, not separately downloaded GGUF
files: the app depends on the registry build's chat template and tool support.

`OLLAMA_NOPRUNE=true` stops Ollama from deleting blobs it does not recognize at
startup, because another app might be using or writing them. Treat a shared
store as read-mostly: update a model by pulling it in one app, and do not run
`ollama rm` against it. Ollama still loads one model at a time
(`OLLAMA_MAX_LOADED_MODELS=1`), and startup checks load models one at a time.
This matters on a mount: gcsfuse reads quickly in sequence but slowly when
several readers interleave.

You can also call the local API directly:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="unused")
response = client.chat.completions.create(
    model="nemotron-3-nano:4b",  # use the tag you selected
    messages=[{"role": "user", "content": "Hello!"}],
)
message = response.choices[0].message
# Reasoning tokens may precede content; leave room for them in the output budget.
print(getattr(message, "reasoning", ""))
print(message.content)
```

## Debugging and validation

```sh
tail -f ~/ollama-server.log
tail -f /tmp/wb-mcp-server.log
curl http://localhost:11434/v1/models
ollama list
nvidia-smi
ollama ps
agent-sandbox status
agent-sandbox logs 200
agent-sandbox selftest
```

| Symptom | Check |
|---|---|
| `the OpenShell gateway is not reachable` | On the VM: `docker logs openshell-gateway`. Gateway state is in `/var/lib/openshell` on the VM |
| Sandbox creation fails | `agent-sandbox status`; on the VM, `docker ps -a --filter label=openshell` and the sandbox's supervisor container logs |
| OpenCode in the sandbox can't reach the model | `agent-sandbox logs` for a denied `host.openshell.internal:11434` request; check that `ollama ps` shows the model and that port 11434 is published on the VM's loopback |
| Something legitimate is blocked | `agent-sandbox logs` shows the program and destination. Add a rule to `/config/openshell/policy.yaml`, then `agent-sandbox policy` |

The regression tests and CI below belong to `src/opencode-nemotron-mcp` and
cover the shared model scripts; they also pass against this folder.
`tests/opencode-nemotron-openshell` covers the model store search
(`python3 -m unittest discover -s tests/opencode-nemotron-openshell`). There are
no automated tests for the OpenShell parts yet; use the self-test on a real app.

Run the GPU-independent regression tests from the repository root:

```sh
go build -o /tmp/wb-mcp-server-test features/src/wb-mcp-server/main.go
export WB_MCP_TEST_BINARY=/tmp/wb-mcp-server-test
python3 -m unittest discover -s tests/opencode-nemotron-mcp -v
```

These cover GPU-aware configuration, `/model` registration, selection, cache
reuse, startup checks (full or selected model only), the model store override,
deferred startup, interactive input, and download/load failures with mocked
Ollama responses. The MCP test uses
the real server binary with a fake `wb` CLI for handshake, tool discovery, and
tool dispatch. It is skipped when `WB_MCP_TEST_BINARY` is unset.

CI also builds the complete devcontainer with its features and runs the installed
OpenCode as `abc`. It checks the model list, MCP connection, and a
Lightning → Nano → Lightning tool round trip in one session against a simulated
OpenAI-compatible server and fake `wb`. It also starts the pinned Ollama with a
model store override and checks the store, prune, load-timeout, and keep-alive
settings in the server's startup log. No weights or GPU are required for these
tests. Workbench lifecycle hooks and CUDA inference still require a real VM.

### Real-GPU acceptance check

After startup, run this in the code-server terminal as `abc`:

```sh
opencode-gpu-check
```

The check alternates between every configured model, with five trials per model.
Each trial sends the entire discovered Workbench MCP tool inventory and configured
instructions through Ollama's `/v1/chat/completions` endpoint, requires a
`wb_wb_status` call with empty arguments, executes only that read-only tool, and
requires a nonempty completed summary. Requests for other tools are failures and
are never executed. It also verifies full GPU residency, configured context, and
one resident model after the requests. It restores the configured default and
exits nonzero if any trial or restoration fails.

Results go to `~/opencode-gpu-check-<timestamp>.json`, including model digests,
timings, context, VRAM, tool count, and individual pass/fail results. Prompts,
workspace results, and generated content are omitted. Use `--repeats 10` for more
trials or `--report /config/my-new-report.json` for a new report path. Run it with
other inference clients idle; concurrent work invalidates the residency check.

This command tests the backend and full MCP inventory, not the interactive TUI
or the exact OpenCode prompt with its additional built-in tools. Before recording,
use `/model` in OpenCode to switch both ways and repeat a read-only workspace
question. The report checks that a summary exists, not its semantic accuracy.
