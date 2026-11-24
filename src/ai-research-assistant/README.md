# AI Research Assistant

Code-server with [OpenCode](https://opencode.ai) running in an
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, on a local
[Nemotron](https://developer.nvidia.com/topics/ai/nemotron) model served by
[vLLM](https://docs.vllm.ai) (Super VL 120B; needs two H100 80 GB). Beta users run only on those
GPUs. On a machine without them, alpha users get a model on Vertex AI in the workspace's project
instead: the same Nemotron model from an endpoint a workspace owner deployed (`deploy-endpoint.sh`,
the vertex-model feature), else Gemini (`VERTEX_MODEL`). Neither is offered inside a data
perimeter.

The app is open to the members of two Workbench groups, beta and alpha; everyone else sees a page
saying the assistant is not yet available. Both groups get the cohort designer, workflow runs and Kumo
forecasts; alpha members also get the Vertex AI models. See "Access" below.

People are trusted more than agents. You keep your Workbench credentials in code-server. The
agent runs in a sandbox that holds no credentials and whose network is deny-by-default: it reads
the workspace's data, writes to what the workspace owns, calls the Workbench core and workflow
tools except the shells and the credential tools, and reaches nothing else. Every connection it attempts is
checked and logged. The policy is part of the image; the app user cannot change it.

Template path: `src/ai-research-assistant`.

## What the app runs

- The agent (OpenCode) in an OpenShell sandbox.
- The Workbench MCP server, with its core and workflow tools.
- The cohort designer and Kumo forecast MCP servers, which are bundled capabilities.
- Nemotron (Super VL) on vLLM. When the machine has no GPUs for it, the
  [`vertex-model`](../../features/src/vertex-model) feature serves in its place, for alpha users
  only, the same model from the workspace's Vertex AI endpoint (`VERTEX_ENDPOINT`), or else Gemini
  on Vertex AI (`VERTEX_MODEL`).

Any workflow registered in the workspace can be run through the Workbench workflow tools, with
the person approving each run (and each registration or cancellation). Parabricks runs that
way, through a workflow: see [`examples/sarek-parabricks`](examples/sarek-parabricks), which
sets up nf-core/sarek with Parabricks DeepVariant as one such workflow.

## How it works

```
code-server (you: Workbench credentials, wb, gcloud, the wb MCP server)
  └─ opencode ──SSH──▶ sandbox-broker ──▶ OpenShell gateway (holds the Docker socket)
                                            └─ creates ──▶ sandbox: OpenCode, non-root, no credentials
                                                             │ every connection checked by OpenShell
                                                             ├─ allowed: the model's chat API (local Nemotron, or Gemini through vertex-model)
                                                             ├─ allowed: BigQuery and Cloud Storage, the workspace's data
                                                             ├─ allowed: the Workbench MCP tools the policy lists
                                                             └─ denied and logged: everything else
```

| Container | Role |
|---|---|
| `application-server` | Code-server, vLLM or the Vertex AI model server, the Workbench MCP server, the cohort designer, the Kumo forecast server. No Docker socket, no route to the gateway |
| `sandbox-broker` | The only container that reaches the gateway. Runs every `agent-sandbox` command for the app, with the image's policy |
| `openshell-gateway` | Creates sandboxes through the VM's Docker socket |
| `opencode-web`, `assistant-ui` | The front door on port 8080: Caddy, and the assistant's UI behind it |
| `port-guard` | Drops connections to port 8080 from other VMs |
| `openshell-init`, `sandbox-image` | Generate the gateway's keys and build the sandbox image, then exit |

The app is built from these features in `features/src`. Each README is the reference for its part:

- [`agent-sandbox`](../../features/src/agent-sandbox): the sandbox, the broker, the audit log.
- [`ai-policy`](../../features/src/ai-policy): the policy file, the data and tool rules, the known gaps.
- [`opencode-harness`](../../features/src/opencode-harness): OpenCode in the sandbox.
- [`vllm-model`](../../features/src/vllm-model): the local model server, Nemotron 3.5 Super VL on 2x H100, and its settings.
- [`cohort-designer`](../../features/src/cohort-designer): the cohort designer the agent drives, and its known limitations.
- [`kumo-forecast`](../../features/src/kumo-forecast): NVIDIA Kumo forecasts for the designer's locked cohorts.
- [`vertex-model`](../../features/src/vertex-model): Gemini on Vertex AI behind vLLM's API, in place of `vllm-model`, for a VM without the GPUs.

## Access

At start, the app checks the person's Workbench groups (`wb group list`) against the image's
`access.yaml` and resolves `features.yaml` (the
[`ai-policy`](../../features/src/ai-policy/README.md) README, "Access and features"):

| Feature | Tier | What it controls |
|---|---|---|
| `cohort_designer` | beta | The cohort designer's MCP server |
| `workflow_runs` | beta | The Workbench workflow tools |
| `kumo_forecast` | beta | The Kumo forecast MCP server |
| `vertex_model` | alpha | Gemini on Vertex AI when the machine cannot run Nemotron |

A person in neither group gets the "not yet available" page, and no sandbox is created. If the check cannot be
made (wb slow or not logged in), the page says so. Until the person is admitted, the app rechecks
in the background every five minutes (two while the check cannot be made) and then starts the
assistant, so someone added to a group does not restart the app; the page reloads within 30
seconds of the change (`~/ai-research-assistant-access.log`). The outcome is in
`/config/.ara/access.json`.

## Usage

Opening the app shows the assistant's UI ([`assistant-ui`](assistant-ui/README.md)). Code-server is at `/ide/`. In a code-server terminal:

```sh
agent-sandbox selftest                     # once, after the first start
agent-sandbox upload ~/repos/<your-repo>   # lands in /sandbox/work/<your-repo>
opencode                                   # the terminal UI, same sandbox and sessions as the web UI
agent-sandbox download <your-repo>         # to ~/sandbox-downloads/
agent-sandbox help                         # status, logs, policy, audit, reset
```

- Every self-test check should pass before you rely on the sandbox.
- The sandbox has its own filesystem: it cannot see `/config`, your repos or the bucket mounts.
  Its files last until `agent-sandbox reset --yes`.
- The first start builds the app and downloads 75 GB of weights; allow about 45 minutes.
  Later starts reuse both.

## What the sandbox contains, and what it doesn't

- The agent (OpenCode) and the code it runs are inside the OpenShell sandbox: no credentials,
  no `wb`, `gcloud` or `bq`, no internet. It can only write to `/sandbox` and `/tmp`.
- The agent's own data access goes from the sandbox straight to the BigQuery and Cloud Storage
  APIs. The credential is the app's own Google credential (the VM's service account), which
  stays at the OpenShell gateway: the sandbox holds a placeholder and the proxy swaps in the
  token only on requests a rule allows. OpenShell checks every request against the data rules
  that `ai-policy.yaml` renders: read the workspace's datasets and buckets, write only to the
  resources the workspace owns, run query jobs only in the workspace's project.
- The MCP servers (Workbench, cohort designer, Kumo forecast) run **outside** the sandbox, in
  the app container, as the app's user, with that user's Workbench credentials. A tool call is
  a remote procedure call: OpenShell's proxy checks its name against the policy (allowed,
  denied, or asked of the person first, which the harness does) and logs it. What the server
  then does runs with the user's access, not the sandbox's.
- So each allowed tool widens what the agent can do, as far as that tool's power goes. That is
  why the tools that run arbitrary commands or SQL as the user (`wb_execute`, `gcloud_execute`,
  `gsutil_execute`, `bq_execute`, `bq_query`) are denied. It is also why each bundled server
  limits itself: the designer queries only the datasets the workspace lists; Kumo writes only
  to the workspace's controlled buckets; starting, registering or cancelling a workflow is
  asked of the person first. A workflow runs on Workbench's compute, with the workspace's
  credentials, not in the sandbox.
- Adding a tool to the image is therefore a security decision. A tool belongs in the image only
  for something the agent can't do itself under the policy, or a bundled capability.

## Policy

One file decides what the agent reaches beyond the local model: `config/ai-policy.yaml` in the
`agent-sandbox` feature. The [`ai-policy` README](../../features/src/ai-policy/README.md) has
the schema and what each setting allows.

- `agent-sandbox policy explain` prints what the running policy allows.
- `agent-sandbox policy` renders it again, after a dataset or bucket is added to the workspace.
- `agent-sandbox logs` shows what was allowed and denied.

## Web UI

Caddy serves the app's port 8080: `/ide/` goes to code-server and everything else to the
assistant's UI ([`assistant-ui`](assistant-ui/README.md)), which reaches OpenCode inside the
sandbox through a port forward the broker keeps. Workbench's proxy does not stream server-sent
events but does carry websockets, so the UI's server relays OpenCode's events over one.


## Limits

- **Workflow runs are driven step by step by the model**, so complex inputs may need the
  person's help.
- **A workflow's outputs stay in the bucket.** The agent reads them but does not load them back
  into the cohort's tables.
- **The assistant's page and code-server share one web origin.** The page shows text from the
  model and from tools, sanitized and under a Content-Security-Policy; the sandbox serves no page
  of its own. A flaw in that sanitizing would be script in your browser on the origin of
  code-server, whose terminal holds your Workbench credentials. Nothing in this app separates
  the two.
- **The access and perimeter checks decide what the app offers, not what the person may reach
  with their own Workbench access.** They are not a boundary against the app's own user, who
  has root in the app container and can edit the state file the checks write.
- **Leaving a group takes effect at the app's next start.** The checks run at each start, and
  until a person is admitted, in the background.
- **The gateway holds the VM's Docker socket** and is unauthenticated. Anything on the VM's
  `openshell-net` can drive it.
- **vLLM (or the Vertex AI model server) and the Workbench MCP server have no authentication.**
  Any process on the VM can call them; the MCP server runs as you, and the Vertex AI model server
  calls Gemini as the VM's service account. Nothing outside the VM can.
- **With Gemini, prompts leave the VM.** They go to Vertex AI in the workspace's project, with
  whatever data the agent read into them.
- **Request bodies are not inspected.** OpenShell sees methods, paths and tool names, not SQL
  or tool arguments. See [Known gaps](../../features/src/ai-policy/README.md#known-gaps).
- **OpenShell 0.1.4 drops requests whose path contains `%2F`.** The sandbox's `wbstorage`
  module works around it for Cloud Storage.
- **port-guard is a host firewall rule set from a container.** Check it from another VM after
  every deployment; the self-test prints the command.
- **The audit trail is partial.** See [Audit log](../../features/src/agent-sandbox/README.md#audit-log).
- **Agents you start yourself in code-server** run with your credentials, outside the sandbox.
  The app installs no coding-assistant CLI.
- **Small counts are kept out of answers by the agent's instructions**, not by code: the agent is
  told never to show a count of people from 1 to 19. Kumo forecasts mask theirs in code; the
  cohort designer's replies carry exact counts.
- **In a workspace inside a data perimeter** (such as All of Us), the app needs two H100 80 GB GPUs:
  the Vertex AI models (the endpoint and Gemini) are off there for everyone, and also whenever the
  app cannot read the workspace's policies. Workflow runs are not supported inside a perimeter yet: its
  batch VMs have no internet to pull workflow containers.

## Troubleshooting

```sh
agent-sandbox status
agent-sandbox logs 200
tail -f ~/vllm-server.log ~/.vertex-model/server.log /tmp/wb-mcp-server.log ~/.cohort-designer/server.log ~/.kumo-forecast/server.log
```

| Symptom | Check |
|---|---|
| The page says the assistant is not yet available ("Thanks for Your Interest") | `jq '.groups, .tier' /config/.ara/access.json`: the groups checked and the tier found. After being added to a group, the assistant starts within about five minutes; `tail ~/ai-research-assistant-access.log` |
| The page says it couldn't verify access | `jq .error /config/.ara/access.json`; `wb auth status`; `tail ~/ai-research-assistant-access.log` |
| The page says the assistant can't run on this app's current configuration, or couldn't start | `jq .model /config/.ara/access.json`; `nvidia-smi`. Without two H100 80 GB GPUs only alpha users get a model (the workspace's endpoint, else Gemini) |
| A tool server shows failed in the side panel | OpenCode connects once; start-services.sh reconnects failed servers at start. By hand: `curl -X POST -d '{}' http://sandbox-broker:4096/mcp/<name>/connect` in a code-server terminal |
| Kumo or the workflow tools are missing | `jq .features /config/.ara/access.json`: they are beta features, on for both groups |
| `the OpenShell gateway is not reachable` | On the VM: `docker logs openshell-gateway` |
| Sandbox creation fails | `agent-sandbox status`, and `/config/openshell/broker-status.txt` |
| OpenCode can't reach the model | `agent-sandbox logs` for a denied `host.openshell.internal:8000`; `curl localhost:8000/v1/models` |
| The `wb` tools are missing in the sandbox | `agent-sandbox policy explain`; `tail /tmp/wb-mcp-server.log` |
| Gemini is refused (`Vertex AI refused a test request` at start) | The VM's service account needs `roles/aiplatform.user` and the Vertex AI API; `tail ~/.vertex-model/server.log` |
| vLLM exits during startup | `tail -n 100 ~/vllm-server.log`. CUDA errors mean the driver is older than 580; out of memory means lowering `VLLM_CONTEXT_LENGTH` or `VLLM_MAX_NUM_SEQS` |
| Something legitimate is blocked | `agent-sandbox logs` shows the program and destination. A dataset or bucket must be in the workspace; a tool or a new destination needs a new image |

Tests: `python3 -m unittest discover -s tests/<suite>` for each of `agent-sandbox`, `ai-policy`,
`ai-research-assistant`, `cohort-designer`, `kumo-forecast`, `opencode-harness`, `vertex-model`
and `vllm-model`, as the CI workflow (`.github/workflows/test-ai-research-assistant.yaml`) runs
them. They do not cover OpenShell or vLLM start-up; use the self-test on a running app.
