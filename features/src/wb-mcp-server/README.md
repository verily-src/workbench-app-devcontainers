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

Rebuild your devcontainer. The server installs at `/opt/wb-mcp-server/wb-mcp-server`.

## Setup

### With Claude CLI

```bash
claude mcp add --transport stdio wb -- /opt/wb-mcp-server/wb-mcp-server
```

### With Gemini CLI

```bash
gemini mcp add --scope user wb /opt/wb-mcp-server/wb-mcp-server
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

## How It Works

### Authentication
- Auto-fetches bearer token from `wb auth print-access-token`
- Refreshes every 55 minutes
- Gets API URLs from `wb status`

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
Test directly:
```bash
/opt/wb-mcp-server/wb-mcp-server
```
Then send:
```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

## Requirements

- Workbench CLI (`wb`) installed
- Authenticated (`wb auth login`)
- Access to data collections and workspaces
