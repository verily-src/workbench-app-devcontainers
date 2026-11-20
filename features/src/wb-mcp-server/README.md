# Workbench MCP Server

MCP server that exposes Workbench APIs for AI agents to discover data, explore schemas, and build cohorts programmatically.

## Installation

Add to your `devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/wb-mcp-server:latest": {}
  }
}
```

Rebuild your devcontainer. The server:
- Installs at `/opt/wb-mcp-server/wb-mcp-server`
- **Runs automatically as HTTP daemon** on port 9242
- **Auto-configures Claude CLI and Gemini CLI** during installation

## How It Works

The server runs in **HTTP mode** as a persistent background service:

- **No lazy loading** - tools are available immediately
- **Port 9242** - uncommon port to avoid conflicts
- **Address 127.0.0.1** - set the feature option `bindAddress`, or `WB_MCP_BIND` when running `start-server.sh`, to listen elsewhere (see Known limitations)
- **Starts via postStartCommand** after authentication completes
- **Pre-configured** with both Claude Code and Gemini CLI

### Manual Setup (if needed)

If auto-configuration failed, manually add the server:

**Claude CLI:**
```bash
claude mcp add --transport http wb http://127.0.0.1:9242
```

**Gemini CLI:**
```bash
gemini mcp add --scope user --transport http wb http://127.0.0.1:9242
```

### Server Control

```bash
# Start server
/opt/wb-mcp-server/start-server.sh

# Stop server
/opt/wb-mcp-server/stop-server.sh

# Check status
pgrep -f 'wb-mcp-server -http'
```

## Tool Groups

Clients send every listed tool's definition to the model with each request. All 116 tools come to about
14,000 tokens, so the server lists only the **core** group by default: 13 tools (about 1,400 tokens) on GCP.

| Group | Tools for |
|---|---|
| `core` (always on) | Status, resources, data collections, app URLs, BigQuery/GCS (GCP) or S3/Aurora (AWS), `wb_execute`, `wb_help` |
| `workflows` | Running, cancelling and debugging workflows: tasks, logs, traces, costs |
| `dataexplorer` | Underlays, studies, cohort building, filters, cohort export |
| `apps` | Creating, deleting, starting and stopping apps |
| `admin` | Workspaces, resources, folders, users, groups, pods, organizations, servers |
| `legacy` | Notebook and cluster tools, and duplicates of other tools (`wb_workspace_list`, `folder_list_tree`, `server_status`, `auth_status`, `version`, `resource_open_console`) |

AWS-only tools are hidden in GCP workspaces and GCP-only tools in AWS workspaces. If the workspace's cloud
isn't known (e.g. `wb status` failed at startup), both are listed.

Enable more groups, as a comma-separated list (`all` for every group):

| Where | How |
|---|---|
| One HTTP client | Add `?toolsets=` to its server URL (on a loopback address; see Known limitations), e.g. `claude mcp add --transport http wb "http://127.0.0.1:9242/?toolsets=core,dataexplorer"` |
| The whole server | Feature option `toolsets`, or `WB_MCP_TOOLSETS` when running `start-server.sh` |
| stdio | `wb-mcp-server -toolsets=core,workflows` |

Calling a tool outside the enabled groups returns an error that names its group. For most tools it
suggests a `wb` command through `wb_execute`; for the tools with no `wb` equivalent (every `dataexplorer` tool,
`workflow_run_logs`, `workflow_run_trace`, `workflow_run_costs` and `workflow_task_get`) it says that the
group must be enabled. Models can call
`wb_help` with topic `toolsets` to see the groups and these instructions, and the long Data Explorer
guides are `wb_help` topics (`cohorts`, `export`, `data-collections`) instead of tool descriptions.

Each tool call is logged (tool name, duration, error flag; not arguments) to `/tmp/wb-mcp-server.log`.

## Quick Examples

The schema and cohort examples need the `dataexplorer` group.

### Find Available Data

```
"List all data collections I can access"
```

Uses `workspace_list_data_collections` to find data collection workspaces.

### Explore Schema

```
"What entities are in the AoU_2024 underlay? Show me the person entity attributes"
```

Uses `underlay_list_entities` and `underlay_get_entity`.

### Create Simple Cohort

```
"Create a cohort called 'seniors' with patients over 65 from the AoU_2024 data collection (workspace ID: abc-123) in my workspace (xyz-456)"
```

Uses `filter_build_attribute` and `cohort_create_in_workspace`.

### Create Complex Cohort

```
"Create a cohort of diabetic seniors: patients over 65 with Type 2 Diabetes (concept 201826) from AoU_2024. Data collection: abc-123, target workspace: xyz-456, name: 'diabetic-seniors'"
```

Uses `filter_build_attribute`, `filter_build_relationship`, `filter_build_boolean_logic`, and `cohort_create_in_workspace`.

## Internals

### Authentication
- Fetches a bearer token from `wb auth print-access-token` and caches it for 30 minutes
- Fetches a new token early if an API call returns 401
- Gets API URLs, the workspace UUID and its Google project from `wb status` at startup

### Latency
Each `wb` CLI call starts a JVM and takes several seconds, so the server avoids it where it can:
- `wb_status` is served from a 30-minute cache (filled at startup, retried every 20 seconds for 15
  minutes while wb is not installed or logged in yet); for a day after that, the old
  result is answered at once while a new one is fetched in the background. `app_list` is served from
  a 30-second cache. Any tool call that may change workspace state clears the `app_list` cache, not
  `wb_status`'s.
- `workspace_list_data_collections` names each collection from a list of every data collection
  the user can read, fetched at startup and kept for an hour; a collection missing from it is
  fetched again, at most once a minute.
- Before each tool call, the server reads `~/.workbench/context.json` (which `wb` updates). If the server or
  workspace changed, for example after `wb workspace set` or `wb workspace create` in a terminal, the server
  uses the new workspace's UUID and Google project and clears the caches.
- Workspace IDs are resolved to UUIDs once and cached.
- `workflow_list` and `workflow_describe` are cached for 10 minutes; a state-changing call (such
  as `workflow_create`) clears them.
- `workflow_job_describe` and `workflow_job_list` (the newest 10 runs; the `limit` argument asks for 1 to 1000) call the workflow manager's
  API, about 3 seconds against 9 to 11 for the CLI, which they fall back to on any error.
- `workflow_job_run` answers within 40 seconds; a submission still running then goes on in the
  background, and the answer says to check `workflow_job_list`. The same run (workflow, inputs,
  params file, profile, outputs and job ID if one is given; not the description) asked for again within 15
  minutes waits on that submission or gets its answer, and is not submitted again. A failed
  submission can be retried at once.
- `bq_execute`, `bq_query`, `gcloud_execute` and `gsutil_execute` run `bq`/`gcloud`/`gsutil` directly in the
  workspace's Google project, not through `wb`. Arguments are split like shell words (quotes and backslashes
  are honored) and the CLI is run directly, without a shell, when it is installed and the command has no
  `$WORKBENCH_*` reference that is unset in the server's environment. Otherwise the call is passed to
  `wb <tool>`, which joins the arguments and runs them through a shell.

### BigQuery
- `bq_query` takes GoogleSQL in its `sql` argument and returns CSV. `maxRows` is 100 by default and
  at most 10,000.
- `bq_execute` takes `bq` arguments (`ls`, `show --schema project:dataset.table`, ...). Bare SQL sent to
  `bq_execute` (also SQL that starts with a comment or a parenthesis) is run as a query.

### Data Collections
Data collection workspaces contain underlays (data models):
- Data collection workspace ID = underlay ID
- Property `"terra-type": "data-collection"`
- Property `"terra-dx-underlay-name"` = underlay name (e.g., "AoU_2024")

### Cohort Creation Flow
1. User has READ access to data collection workspace
2. User has WRITER access to target workspace
3. Server creates:
   - Study in Data Explorer (if doesn't exist)
   - Cohort in that study
   - Controlled resource in workspace

### Filter Structure
Filters use Data Explorer's filter format:
- **Attribute**: `age > 65`, `gender = 'male'`
- **Relationship**: `persons who have condition = diabetes`
- **Boolean Logic**: Combine with AND/OR/NOT
- **Hierarchy**: All descendants of concept

Filter builders output correct JSON for you.

## Troubleshooting

### "Error: failed to get access token"
```bash
wb auth login
```

### "API error (403)"
Check permissions:
```bash
wb workspace describe <workspace-id>
```
Need READER on data collections, WRITER on target workspace.

### "Error: underlayName parameter is required"
First find underlay names:
```
"List my data collections and show their underlay names"
```

### Server not responding

Check if the server is running:
```bash
pgrep -f 'wb-mcp-server -http'
```

If not running, start it:
```bash
/opt/wb-mcp-server/start-server.sh
```

Test the HTTP endpoint:
```bash
curl -X POST http://127.0.0.1:9242 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Check logs:
```bash
tail -f /tmp/wb-mcp-server.log
```

## Known limitations

- The HTTP server has no authentication. It listens on `127.0.0.1` by default, so only processes in
  the container can reach it. With any other `bindAddress` (or `WB_MCP_BIND`), such as `0.0.0.0`, anything
  that can reach the port can call every tool, including `wb_execute`, and the call runs as the
  user the server runs as. Use another address only on a network where every caller is trusted.
- `?toolsets=` is not an access control on loopback (`127.0.0.0/8`, `::1`, `localhost`): any client
  can enable any group, including `admin`. With any other `bindAddress`, the server's `toolsets`
  setting is the most a client gets, and `?toolsets=` can only narrow it.

## Requirements

- Workbench CLI (`wb`) installed
- Authenticated (`wb auth login`)
- Access to data collections and workspaces

## Workflow diagnostics

These seven read-only tools call Workflow Manager directly:

| Tool | Purpose |
| --- | --- |
| `workflow_inputs_get` | Parsed inputs for a workflow resource |
| `workflow_task_list` | Tasks with status/time/search filters, sorting and pagination |
| `workflow_task_get` | Details of one task |
| `workflow_run_logs` | Paginated run logs, optionally restricted to a task |
| `workflow_run_trace` | Nextflow trace data |
| `workflow_run_costs` | GCP-attributed costs for 1–1000 runs |
| `workflow_batch_status_counts` | Counts of child runs by status |

All require an explicit `workspaceId` UUID. Workflow, run and task IDs also use
API UUIDs, not CLI display names or engine-native job IDs. Paginated tools return
the backend response unchanged; pass its next-page token as `pageToken`.

The endpoint is read on each call from `server.workflowManagerUri` in
`~/.workbench/context.json`, honoring `WORKBENCH_CONTEXT_PARENT_DIR`. Authentication
uses `wb auth print-access-token`. Missing context fails explicitly; there is no
production fallback. IAP-protected servers are not supported by these new tools.

Example MCP tool arguments for logs:

```json
{"name":"workflow_run_logs","arguments":{"workspaceId":"11111111-1111-4111-8111-111111111111","runId":"22222222-2222-4222-8222-222222222222","limit":100}}
```

Run local tests with `go test ./...` from this directory. Tests use a temporary CLI
context, a fake `wb` executable and an HTTP transport stub; they do not access
Workbench or verify deployment-specific permissions and engine support.
