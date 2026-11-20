# agent-sandbox

Runs an AI agent in an [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandbox that
holds no credentials and reaches only the local model, the workspace's data and the Workbench
tools, as the administrator's `ai-policy.yaml` allows. Every connection is checked and logged.
A workspace user can start, use and reset the sandbox, not change what it may reach.

The agent itself is a [harness](#harness), installed by a harness feature such as
`opencode-harness`. The app's compose file provides what a feature cannot: the OpenShell
gateway, the sandbox-broker and the sandbox image build. `src/ai-research-assistant` is
the reference app.

```json
"features": {
  "./.devcontainer/features/ai-policy": {},
  "./.devcontainer/features/agent-sandbox": {"username": "abc", "userHomeDir": "/config"},
  "./.devcontainer/features/opencode-harness": {"username": "abc", "userHomeDir": "/config"}
}
```

| Option | Default | Meaning |
|---|---|---|
| `username`, `userHomeDir` | `root`, `/root` | The app user, whose home holds the sandbox state (`openshell/`) and downloads |
| `role` | `app` | `app`: every command goes to the broker. `broker`: the sandbox-broker image; adds sshd and runs the commands against the gateway |
| `openshellVersion`, `openshellSha256` | `0.1.4` | The OpenShell CLI; the gateway and runtime images in the compose file must match |

The feature installs `/opt/agent-sandbox` and the `agent-sandbox` command (`agent-sandbox help`).
The policy files are in `config/`: `ai-policy.yaml`, the administrator's, and `policy.yaml`,
the base OpenShell policy (filesystem, Landlock, the local model's chat API). An app that needs
other settings ships its own folder and names it in `AGENT_SANDBOX_CONFIG`.

## Reading order

Seven files carry the security boundary. The rest is support.

1. `broker/sshd_config`: one user, one key source, one forced command.
2. `broker/authorized-keys.sh`: the key sshd accepts.
3. `broker/command.sh`: the command allowlist, and how arguments arrive.
4. `broker/entrypoint.sh`: the account, the environment sessions get, the credential refresh.
5. `agent-sandbox.sh`: `ensure_policy` (the render), `ensure_provider` (the credential),
   `ensure_sandbox` (creation).
6. `config/policy.yaml`: the base OpenShell policy.
7. `config/ai-policy.yaml`: the administrator's policy, which `render-policy.py` in the
   `ai-policy` feature compiles.

## Environment the app sets

| Variable | Where | Meaning |
|---|---|---|
| `APP_USER_HOME` | app, broker | The user's home (default `/config`) |
| `AGENT_BROKER` | app | The sandbox-broker's host name on the compose network |
| `AGENT_MODEL_URL` | app, broker | Where the sandbox reaches the model's OpenAI-compatible API (default `http://host.openshell.internal:8000/v1`) |
| `AGENT_MODEL`, or `AGENT_MODEL_COMMAND` | app | The model the harness uses, or a command that prints it |
| `AGENT_CONTEXT_LENGTH` | broker | The model's context length (default 65536) |
| `AGENT_MCP_URL` | app, broker | Where the sandbox reaches the Workbench MCP server; unset means no tools rule |
| `AGENT_MCP_SERVERS` | app, broker | Other MCP servers published to the sandbox, `name=url` separated by spaces ("Other MCP servers") |
| `AGENT_ACCESS_STATE` | broker | The access state the app writes (the ai-policy README, "Access and features"). Set, no sandbox is created or updated unless it admits the person, and the features that are off for them stay out of the policy. Unset, no gate |
| `AGENT_ACCESS_COMMAND` | app | A command that rewrites the access state; `agent-sandbox policy` runs it first |
| `OPENSHELL_GATEWAY_ENDPOINT` | broker | The gateway (default `http://openshell-gateway:8080`) |

## Other MCP servers

An app can publish MCP servers to the sandbox beside the Workbench one. It names them in
`AGENT_MCP_SERVERS` as `name=url`, separated by spaces, and the feature that installs a server
puts its catalog in `mcp.d/<name>.yaml`:

```yaml
name: cohort                 # also the prefix the harness gives the tools: cohort_<tool>
title: Cohort designer
tools: [send_message, ...]   # every tool the server has; a tool not listed is not callable
ask: [respond_approval]      # the harness asks the person before each call of these
instructions: |              # what the agent is told, in /sandbox/data-access.md
  ...
```

Each server gets its own OpenShell `mcp` rule (`mcp_<name>`), with `tools/call` allowed only
for the catalog's tools. `tools.deny` in `ai-policy.yaml` applies to them by tool name, and
`tools.allow: none` turns them off; the tool groups are the Workbench server's and do not.
The shipped `ai-policy.yaml` allows the `core` and `workflows` groups of the Workbench server.

The Workbench server's own tools can be asked about too: `tool-groups.yaml`'s `ask:` list names
the tools (workflow create, run and cancel) the harness asks the person about before each call.
The `cohort-designer` and `kumo-forecast` features each install one such server today.

## Harness

A harness is the agent program the sandbox runs, described by one YAML file in `harnesses/`.
The app runs the one its first harness feature installed; a user cannot switch it.
`opencode.yaml` in the `opencode-harness` feature is the worked example.

| Field | Meaning |
|---|---|
| `name` | Names the sandbox, `agent-<name>` |
| `image` | Image the sandbox is created from (the app's compose file builds it) |
| `binaries` | Real paths of the programs allowed to call the model's chat API and the Workbench tools |
| `command`, `workdir`, `env` | What to run, where, and its environment. Arguments to `agent-sandbox run` are appended |
| `serve` (optional) | A web server the sandbox runs as its main process; its port is forwarded so the app can reach it (the assistant UI talks to it) |
| `config` (optional) | A hook that prints the harness's configuration, and the variable the sandbox gets it in. The hook runs on the broker with `MODEL_BASE_URL`, `AGENT_MODEL`, `AGENT_CONTEXT_LENGTH`, `AGENT_MCP_URL`, `AGENT_POLICY_SUMMARY` |
| `selftest` (optional) | Arguments to run and a `grep -E` pattern the output must match |

Every harness gets `MODEL_BASE_URL` and `AGENT_MODEL`. A harness file cannot widen the policy;
it only names which programs use the endpoints. The agent is told what it may reach in
`/sandbox/data-access.md`.

## Admin-locked mode

The app user is root in the app container. A policy file or a gateway within that container's
reach would be theirs to change, so both are kept out of it.

```
app (code-server, the user)          sandbox-broker                 openshell-gateway
  agent-sandbox ──SSH, one command──▶ sshd ForceCommand ──────────▶ gateway API
  network: app-network                 the image's policy files       Docker socket
                                       networks: both                 network: openshell-net
```

- **Network.** The gateway is on `openshell-net`. The broker is the only container on both
  networks.
- **Commands.** `broker-client.sh` sends the argument list as one base64 string.
  `broker/command.sh`, sshd's `ForceCommand`, decodes it, allows a fixed set of `agent-sandbox`
  commands and runs them as the app's user. Nothing the client sends is evaluated as shell.
- **Policy.** The policy files and the harness are the broker image's. Each render goes to a
  directory of the broker's own, read-only once written, and the gateway is given that file.
  What appears in `/config/openshell` is a copy to read. A command that uses an existing
  sandbox renders again and, if the render differs from the one the sandbox last received
  (a digest kept beside the copy), applies it first; if the gateway does not take it, the command
  stops rather than run on the old policy. Network rules change live; filesystem and process
  settings need `reset`.
- **The user's home.** It is the broker's `HOME` and working directory, and the app can write
  it. The broker loads no Python packages from it, and its `jq` and `curl` ignore the
  `.jq` and `.curlrc` there, but it does read two inputs from files the user can write: the
  workspace's identity (`~/.workbench/context.json`) and the access state
  (`/config/.ara/access.json`, the tier and the features).
- **The app folder** (the compose file, `gateway.toml`) is not mounted into the app.
- **Key.** The user's ed25519 key in `~/.ssh/sandbox-broker` opens only the forced command.
  Anyone in the app container may use it.

A user can run the agent, open a shell in the sandbox, move files in and out, read the logs and
reset the sandbox. A user cannot add a destination, widen the policy files or the tool
allow-list (both come from the broker image), switch the harness or reach the gateway. The
workspace and the access state are inputs the user controls (see below). The sandbox binds the
agent, not the app's user, and this bounds the agent's reach, not the user's own access.

## Known limitations

- **The app's user chooses two inputs of the render.** The broker reads the workspace's identity
  from `~/.workbench/context.json` and the access tier and features from
  `/config/.ara/access.json`, both writable by the user. The user can change which workspace's
  data rules are rendered and which features are on. The policy files and the tool allow-list
  stay the image's.
- **The record of the policy last applied is a file in the user's home.** A user can edit it so
  that a changed render is not applied by the next command; `agent-sandbox policy` applies it
  whatever the record says.
- **An agent's own child processes can call the allowed MCP servers and tools directly.** A
  program the agent runs from its shell tool (curl, for example) reaches the same endpoints as
  the harness, without the approval prompt the harness shows. What must not happen without a
  person goes in `tools.deny`. See "Known gaps" in the [ai-policy README](../ai-policy/README.md#known-gaps).

## Audit log

OpenShell logs every network decision the sandbox makes, allowed or denied, with the program,
the destination, the rule and, for Workbench tools, the tool name. It does not log commands or
file activity inside the sandbox.

| Record | Where | Lifetime |
|---|---|---|
| The sandbox's decisions | The gateway's memory, last 2,000 lines | Lost when the sandbox is deleted or the gateway restarts. `agent-sandbox audit save` and `reset` copy them to `/config/openshell/audit/` |
| Gateway events (sandbox created, policy updated) | `/var/lib/openshell/audit/` on the VM | Empty on OpenShell 0.1.4, and not reachable from the app |
| Full JSON records of the decisions | The supervisor container's stderr, on the VM | Not reachable from the app. Keeping them needs a collector on the VM |

`agent-sandbox audit export gs://<bucket>/<folder>` saves and copies to a bucket. Nothing
exports in the background, so the durable record is what you export.

Tests: `python3 -m unittest discover -s tests/agent-sandbox`. The isolation itself is checked
on a running app by `agent-sandbox selftest`.
