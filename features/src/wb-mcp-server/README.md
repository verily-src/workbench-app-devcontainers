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

## Quick Examples

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
- `wb_status` is served from a 5-minute cache (filled at startup), and `app_list` from a 30-second cache.
  Any tool call that may change workspace state clears these caches.
- Workspace IDs are resolved to UUIDs once and cached.
- `bq_execute`, `bq_query`, `gcloud_execute` and `gsutil_execute` run `bq`/`gcloud`/`gsutil` directly in the
  workspace's Google project, not through `wb`. Arguments are split like shell words (quotes and backslashes
  are honored) but never run through a shell. If the CLI isn't installed, or the command uses a
  `$WORKBENCH_*` variable that isn't set in the server's environment, the call falls back to `wb <tool>`.

### BigQuery
- `bq_query` takes GoogleSQL in its `sql` argument and returns CSV.
- `bq_execute` takes `bq` arguments (`ls`, `show --schema project:dataset.table`, ...). Bare SQL sent to
  `bq_execute` is run as a query.

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

## Requirements

- Workbench CLI (`wb`) installed
- Authenticated (`wb auth login`)
- Access to data collections and workspaces
