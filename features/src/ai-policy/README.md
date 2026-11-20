# ai-policy

Compiles an administrator's AI policy, one file, into the
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) policy an agent sandbox runs under.
The `agent-sandbox` feature runs it.

```json
"features": {
  "./.devcontainer/features/ai-policy": {}
}
```

## The policy an administrator writes

`ai-policy.yaml`, baked into the app image. The `agent-sandbox` feature ships this default in
its `config/` folder:

```yaml
version: 1
data:
  read: workspace         # workspace | none
  write: controlled       # controlled | none
tools:
  allow: all              # all | none | [group, ...]
  deny: [wb_execute, gcloud_execute, gsutil_execute, git_execute, aurora_resolve_connection, bq_execute, bq_query]
```

| Key | Effect |
|---|---|
| `data.read` | `workspace`: the agent may read every BigQuery dataset and Cloud Storage bucket the workspace lists. `none`: no data and no credential |
| `data.write` | `controlled`: it may also write to the resources the workspace owns. Referenced resources, a data collection's among them, stay read-only. `none`: read-only everywhere |
| `tools.allow` | Which groups of Workbench MCP tools the agent may call. The groups are in the `agent-sandbox` feature's `tool-groups.yaml` |
| `tools.deny` | Tools never callable, whatever the groups say |

Workbench tools can also be asked about: the `ask:` list in `tool-groups.yaml` names the tools
the harness asks the person about before each call (the ones that start or stop paid compute or
register something in the workspace). `render-policy.py` writes the allowed ones into the
summary's `tools.ask`.

A file with another `version`, an unknown key or group, or a repeated key is refused, and no
sandbox is created.

Workbench's own access still applies: the agent acts as the user, so IAM and data collection
policies bind it too. This file only removes access.

## Data access

The sandbox reaches Google's APIs with the app's own credential: the token of the service
account the VM runs as, read from the metadata server and renewed by the broker. The token
stays at the OpenShell gateway. The sandbox sees a placeholder, and the proxy swaps in the real
token only on requests a rule allows.

`workspace-data.py` reads the workspace's resources from the Workspace Manager API on every
render, and only from `workbench.verily.com`. If Workbench cannot be read, or the metadata
server gives no credential, no data rules are rendered.

| Restriction | How |
|---|---|
| Only the workspace's data | `GET` on the listed buckets and datasets, and dataset listing in their projects |
| Writes only where the workspace owns | Uploads and deletes in owned buckets; table changes in owned datasets |
| Jobs in the workspace's project | Query jobs run only there, so nothing is billed elsewhere |
| One interpreter | The rules name `/usr/bin/python3.11`. `curl`, `bq` and `gsutil` are blocked |

In the sandbox, Cloud Storage objects are read and written with the `wbstorage` module, not the
`google.cloud.storage` client, whose percent-encoded object paths OpenShell 0.1.4 drops. The
BigQuery Storage Read API is not allowed; read dataframes with `create_bqstorage_client=False`.
The `wbdata` module describes the datasets the data notes list in one call (`python -m wbdata
survey`: tables, rows and date columns; `describe` for columns; `find` to search column names),
from each dataset's `__TABLES__` and `INFORMATION_SCHEMA.COLUMNS`, so the agent does not read
tables one at a time to learn what is there.

### Known gaps

OpenShell rules see the method and the path, not the request body or headers.

- **BigQuery SQL.** A `DELETE FROM` or `DROP TABLE` is a query job like any other. A statement
  can name any table the app's identity can read, in any project, and `EXPORT DATA` or a
  destination table writes wherever that identity can write.
- **Cloud Storage copies.** An upload to an owned bucket may carry `x-goog-copy-source`, which
  copies from any bucket the app's identity can read.
- **Tool arguments.** A Workbench tool is allowed or denied by name. What an allowed tool does
  with its arguments is the server's and Workbench's to govern.
- **Programs the agent runs.** OpenShell authorizes a connection by its executable or by any
  ancestor's. OpenCode is named on the model and MCP endpoints, so every program the agent runs
  from OpenCode's shell reaches them too: a script can call an MCP tool directly. The tool rules
  still allow and deny tools by name, but a tool behind OpenCode's permission prompt (a catalog's
  `ask`, such as the designer's `respond_approval` or `workflow_job_run`) is not asked about when
  called that way.

For the first three, the bound is Workbench: IAM, read-only resources and data policies. Keep
the app's identity narrow. For the last, a permission prompt is a check on the model, not a
boundary: what must not happen without a person goes in `tools.deny`.

## Workbench tools

The app publishes the Workbench MCP server to the sandbox, and OpenShell proxies it as an `mcp`
endpoint: the handshake and `tools/list` are allowed, and `tools/call` only for the tool names
the policy allows. A tool in no group is not callable. Calls run in the app with the user's own
Workbench access.

The shipped policy allows the `core` and `workflows` groups and none of the others (admin, apps,
data explorer, legacy), whatever toolsets the server offers a client. It denies the tools that run arbitrary commands as the user, the ones that hand out
credentials, and `bq_execute` and `bq_query`, which would run SQL outside the sandbox's data rules.

An app's other MCP servers (`--server`, the agent-sandbox README, "Other MCP servers") each
get a rule of the same shape, `mcp_<name>`, from the server's own catalog of tools.

## Access and features

Two more files beside `ai-policy.yaml` decide who may use the app and which of its features they
get. `access.py` reads them.

- `access.yaml`: the Workbench organization and one group per tier, `beta` and `alpha`. Being in
  either group (as a member or an admin) admits a person; the alpha group also turns on the
  alpha features. The app only reads membership (`wb group list`), and only of groups in that
  organization. Nothing at run time replaces the groups: changing them is a change to the
  image.
- `features.yaml`: each feature's minimum tier and what it controls: MCP servers (`servers`)
  and Workbench tool groups (`tool_groups`). A feature that is off for a person leaves those out
  of the sandbox policy and out of the harness's configuration.

```
access.py check   [--config-dir DIR]     # DIR defaults to the image's /opt/agent-sandbox/config
access.py resolve --state access.json [--config-dir DIR] [--timeout 180]
access.py model   --state access.json --gpus CSV [--vllm-up] [--vertex-model M] [--vllm-model M]
access.py model-failed --state access.json --message TEXT
access.py model-name --state access.json
```

`resolve` runs `wb group list --format=json --org=<org>` as the person, reads the policies of the
app's workspace from Workbench's workspace API, and writes the state file. The workspace is the one
the VM's metadata names (`terra-workspace-id`), not the CLI's current one, so `wb workspace set`
does not change the answer. A workspace with the
`terra/exfil-perimeter-constraint` policy is inside a data perimeter (such as All of Us): there
the `vertex_model` feature (the endpoint and Gemini) is off whatever the tier, since it sends data
to a model service outside the VM. It is also off when the policies cannot be read: no answer, an
answer for another workspace, or one without a list of policies. The state file holds:
`status` (`ok`, or `error` when the check could not be made), `tier` (`alpha`, `beta` or none),
`features` (each on or off), `off` (the servers and tool groups to leave out) and `message` (what
the page shows a person it does not admit). It exits 0 when the check was made, 2 when it could
not be (wb failed, timed out, or anything else went wrong, so it is retried), 1 when the
configuration is invalid (not retried; the page says to fix it). Both failures write an `error`
state with every feature off, so nothing reads a stale admission.
At each start of the app, start-services.sh removes the state file before its first `resolve`, so
until that finishes (up to 180 s) the page and the broker see no state and refuse; the rechecks
after it keep the last state while they run.

`model` adds the model the app serves: the local model when the machine has the GPUs it
needs (two of 79,000 MiB or more, such as two H100 80 GB) or vLLM already answers for it (`--vllm-up`; the Vertex AI proxy on the same port does not count); else, only for a person with
the `vertex_model` feature (alpha, never inside a data perimeter), the Nemotron model a Vertex AI
endpoint in the workspace's project serves (`--endpoint-model`, which the vertex-model feature's
`find-endpoint` found), else Gemini on Vertex AI; else none, with a message for the page. `model-failed` replaces
it with no model and a message, when the app could not start the one it chose. `model-name`
prints the chosen model, for `AGENT_MODEL_COMMAND`. A later `resolve` (`agent-sandbox policy`) keeps the model,
since nothing restarts it; a Vertex AI model stays only while the person still has `vertex_model`.

Unknown keys, tiers, versions, servers or tool groups are refused, as in `ai-policy.yaml`. The
check runs in the app container as the app's user, who can also edit the state file: it decides
what the app offers, not what the person may reach with their own Workbench access.

Access is checked when the app starts and by `agent-sandbox policy`; once admitted, nothing
rechecks it on a timer. A check that no longer admits the person closes the page and the
assistant UI's OpenCode routes, but a sandbox that is already running keeps its policy and its
MCP servers until the app restarts or the sandbox is reset.

## The compiler

```
render-policy.py policy.yaml ai-policy.yaml --harness harness.json
    [--workspace workspace-data.json] [--tools tool-groups.yaml --mcp-url URL]
    [--server NAME URL catalog.yaml]... [--summary summary.json] [--access access.json]
```

`--access` leaves out the servers and tool groups in the state's `off` lists ("Access and
features").

`render-policy.py` combines the base `policy.yaml`, `ai-policy.yaml`, the harness's binaries
and the workspace's resources into the effective policy, with `enforcement: enforce` on every
endpoint. `ai_policy.py` is the schema.

Tests: `python3 -m unittest discover -s tests/ai-policy`.
