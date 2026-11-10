# AI Research Assistant

Code-server with [OpenCode](https://opencode.ai) running in an
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox, on a local
[Nemotron](https://developer.nvidia.com/topics/ai/nemotron) model served by
[vLLM](https://docs.vllm.ai) (Lightning 30B; needs an A100 40 GB or larger).

People are trusted more than agents. You keep your Workbench credentials in code-server. The
agent runs in a sandbox that holds no credentials and whose network is deny-by-default: it reads
the workspace's data, writes to what the workspace owns, calls the Workbench tools except the
shells and the credential tools, and reaches nothing else. Every connection it attempts is
checked and logged. The policy is part of the image; the app user cannot change it.

Template path: `src/ai-research-assistant`.

## How it works

```
code-server (you: Workbench credentials, wb, gcloud, the wb MCP server)
  └─ opencode ──SSH──▶ sandbox-broker ──▶ OpenShell gateway (holds the Docker socket)
                                            └─ creates ──▶ sandbox: OpenCode, non-root, no credentials
                                                             │ every connection checked by OpenShell
                                                             ├─ allowed: vLLM chat API (local Nemotron)
                                                             ├─ allowed: BigQuery and Cloud Storage, the workspace's data
                                                             ├─ allowed: the Workbench MCP tools the policy lists
                                                             └─ denied and logged: everything else
```

| Container | Role |
|---|---|
| `application-server` | Code-server, vLLM, the Workbench MCP server. No Docker socket, no route to the gateway |
| `sandbox-broker` | The only container that reaches the gateway. Runs every `agent-sandbox` command for the app, with the image's policy |
| `openshell-gateway` | Creates sandboxes through the VM's Docker socket |
| `opencode-web`, `opencode-web-events` | The front door on port 8080: Caddy and the event bridge |
| `port-guard` | Drops connections to port 8080 from other VMs |
| `openshell-init`, `sandbox-image` | Generate the gateway's keys and build the sandbox image, then exit |

The app is built from four features in `features/src`. Each README is the reference for its part:

- [`agent-sandbox`](../../features/src/agent-sandbox): the sandbox, the broker, the audit log.
- [`ai-policy`](../../features/src/ai-policy): the policy file, the data and tool rules, the known gaps.
- [`opencode-harness`](../../features/src/opencode-harness): OpenCode in the sandbox.
- [`vllm-model`](../../features/src/vllm-model): the model server and its settings.

## Usage

Opening the app shows OpenCode's web UI. Code-server is at `/ide/`. In a code-server terminal:

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
- The first start builds the app and downloads 21.6 GB of weights; allow about 45 minutes.
  Later starts reuse both.

## Policy

One file decides what the agent reaches beyond the local model: `config/ai-policy.yaml` in the
`agent-sandbox` feature. The [`ai-policy` README](../../features/src/ai-policy/README.md) has
the schema and what each setting allows.

- `agent-sandbox policy explain` prints what the running policy allows.
- `agent-sandbox policy` renders it again, after a dataset or bucket is added to the workspace.
- `agent-sandbox logs` shows what was allowed and denied.

## Web UI

Caddy (`caddy/Caddyfile`) serves the app's port 8080: the root goes to OpenCode's web UI inside
the sandbox, through a port forward the broker keeps, and `/ide/` goes to code-server. Until
the sandbox is up the root answers 503.

Workbench's proxy does not stream server-sent events, which the UI depends on, but it does
carry websockets. `event-bridge/` therefore adds one script to the UI's page and relays the
event stream over a websocket.

## Limits

- **The agent's web UI and code-server share one web origin.** A page served from the sandbox
  is script in your browser on the origin of code-server, whose terminal holds your Workbench
  credentials, and a process in the sandbox could replace the UI's server. Nothing in this app
  separates the two.
- **The gateway holds the VM's Docker socket** and is unauthenticated. Anything on the VM's
  `openshell-net` can drive it.
- **vLLM and the Workbench MCP server have no authentication.** Any process on the VM can call
  them, and the MCP server runs as you. Nothing outside the VM can.
- **Request bodies are not inspected.** OpenShell sees methods, paths and tool names, not SQL
  or tool arguments. See [Known gaps](../../features/src/ai-policy/README.md#known-gaps).
- **OpenShell 0.1.4 drops requests whose path contains `%2F`.** The sandbox's `wbstorage`
  module works around it for Cloud Storage.
- **port-guard is a host firewall rule set from a container.** Check it from another VM after
  every deployment; the self-test prints the command.
- **The audit trail is partial.** See [Audit log](../../features/src/agent-sandbox/README.md#audit-log).
- **Agents you start yourself in code-server** run with your credentials, outside the sandbox.

## Troubleshooting

```sh
agent-sandbox status
agent-sandbox logs 200
tail -f ~/vllm-server.log /tmp/wb-mcp-server.log
```

| Symptom | Check |
|---|---|
| `the OpenShell gateway is not reachable` | On the VM: `docker logs openshell-gateway` |
| Sandbox creation fails | `agent-sandbox status`, and `/config/openshell/broker-status.txt` |
| OpenCode can't reach the model | `agent-sandbox logs` for a denied `host.openshell.internal:8000`; `curl localhost:8000/v1/models` |
| The `wb` tools are missing in the sandbox | `agent-sandbox policy explain`; `tail /tmp/wb-mcp-server.log` |
| vLLM exits during startup | `tail -n 100 ~/vllm-server.log`. CUDA errors mean the driver is older than 580; out of memory means lowering `VLLM_CONTEXT_LENGTH` or `VLLM_MAX_NUM_SEQS` |
| Something legitimate is blocked | `agent-sandbox logs` shows the program and destination. A dataset or bucket must be in the workspace; a tool or a new destination needs a new image |

Tests: `python3 -m unittest discover -s tests/<suite>` for `vllm-model`, `ai-policy`,
`agent-sandbox`, `opencode-harness` and `ai-research-assistant`. They do not cover
OpenShell or vLLM start-up; use the self-test on a running app.
