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
  deny: [wb_execute, gcloud_execute, gsutil_execute, git_execute, resource_credentials, aurora_resolve_connection, bq_execute]
```

| Key | Effect |
|---|---|
| `data.read` | `workspace`: the agent may read every BigQuery dataset and Cloud Storage bucket the workspace lists. `none`: no data and no credential |
| `data.write` | `controlled`: it may also write to the resources the workspace owns. Referenced resources, a data collection's among them, stay read-only. `none`: read-only everywhere |
| `tools.allow` | Which groups of Workbench MCP tools the agent may call. The groups are in the `agent-sandbox` feature's `tool-groups.yaml` |
| `tools.deny` | Tools never callable, whatever the groups say |

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

### Known gaps

OpenShell rules see the method and the path, not the request body or headers.

- **BigQuery SQL.** A `DELETE FROM` or `DROP TABLE` is a query job like any other. A statement
  can name any table the app's identity can read, in any project, and `EXPORT DATA` or a
  destination table writes wherever that identity can write.
- **Cloud Storage copies.** An upload to an owned bucket may carry `x-goog-copy-source`, which
  copies from any bucket the app's identity can read.
- **Tool arguments.** A Workbench tool is allowed or denied by name. What an allowed tool does
  with its arguments is the server's and Workbench's to govern.

For all three, the bound is Workbench: IAM, read-only resources and data policies. Keep the
app's identity narrow.

## Workbench tools

The app publishes the Workbench MCP server to the sandbox, and OpenShell proxies it as an `mcp`
endpoint: the handshake and `tools/list` are allowed, and `tools/call` only for the tool names
the policy allows. A tool in no group is not callable. Calls run in the app with the user's own
Workbench access.

The default denies the tools that run arbitrary commands as the user, the ones that hand out
credentials, and `bq_execute`, which would run SQL outside the sandbox's data rules.

## The compiler

```
render-policy.py policy.yaml ai-policy.yaml --harness harness.json
    [--workspace workspace-data.json] [--tools tool-groups.yaml --mcp-url URL] [--summary summary.json]
```

`render-policy.py` combines the base `policy.yaml`, `ai-policy.yaml`, the harness's binaries
and the workspace's resources into the effective policy, with `enforcement: enforce` on every
endpoint. `ai_policy.py` is the schema.

Tests: `python3 -m unittest discover -s tests/ai-policy`.
