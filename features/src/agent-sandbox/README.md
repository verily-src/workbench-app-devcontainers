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
| `OPENSHELL_GATEWAY_ENDPOINT` | broker | The gateway (default `http://openshell-gateway:8080`) |

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
| `serve` (optional) | A web server the sandbox runs as its main process; its port is forwarded for the app's front door |
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
  What appears in `/config/openshell` is a copy to read.
- **The user's home.** It is the broker's `HOME` and working directory, and the app can write
  it, so Python on the broker loads nothing from it.
- **The app folder** (the compose file, `gateway.toml`) is not mounted into the app.
- **Key.** The user's ed25519 key in `~/.ssh/sandbox-broker` opens only the forced command.
  Anyone in the app container may use it.

A user can run the agent, open a shell in the sandbox, move files in and out, read the logs and
reset the sandbox. A user cannot add a destination, change the data or the tools, switch the
harness or reach the gateway. This bounds the agent's reach, not the user's own access.

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
