# LLM Context Generator (llm-context)

Generates `~/CLAUDE.md` context file for LLMs (Claude Code, Gemini CLI, etc.) with Workbench workspace information. Claude Code auto-discovers this file on startup.

## Example Usage

```json
"features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/llm-context:1": {
        "username": "jupyter",
        "userHomeDir": "/home/jupyter"
    }
}
```

Or for local development:

```json
"features": {
    "./.devcontainer/features/llm-context": {
        "username": "jupyter",
        "userHomeDir": "/home/jupyter"
    }
}
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| username | Username of the container user | string | root |
| userHomeDir | Home directory of the container user | string | /root |

## What It Does

When installed, this feature:

1. **Generates `~/CLAUDE.md`** - Claude Code auto-discovers this file on startup
2. **Provides workspace context** - Name, ID, role, resources, cloud paths
3. **Includes skill files** - Detailed guides (e.g., custom app creation) in `~/.workbench/skills/`
4. **Sets up aliases** - `generate-llm-context`, `refresh-context`

## What's in `~/CLAUDE.md`

- **Quick Rules** - When to use this file vs. MCP/CLI
- **Current Workspace** - Name, ID, description, role, cloud platform
- **Resource Paths** - JSON lookup for all resources (GCS, BigQuery, etc.)
- **Data Persistence** - Warning + save commands
- **Data Exploration** - Common BigQuery/GCS commands
- **MCP Tools** - Available tools and CLI equivalents
- **Skills** - Links to detailed guides

## When Context Gets Generated

1. **On first terminal open** - Via `.bashrc` trigger (runs in background)
2. **Manually** - Run `generate-llm-context` or `refresh-context`

## MCP Integration

This feature works well alongside the `wb-mcp-server` feature:
- **`llm-context`** provides static context (workspace info, resource paths)
- **`wb-mcp-server`** provides dynamic tools (search, create, modify)

For optimal LLM experience, use both:

```json
"features": {
    "./.devcontainer/features/llm-context": {},
    "./.devcontainer/features/wb-mcp-server": {}
}
```

## Troubleshooting

### Context not generating?

```bash
# Check if workspace is set
wb workspace describe

# If not authenticated:
wb auth login --mode=APP_DEFAULT_CREDENTIALS
wb workspace set <workspace-id>

# Then generate manually:
generate-llm-context
```

### Claude Code not seeing context?

```bash
# Check file exists
ls -la ~/CLAUDE.md

# Check it's not empty
head ~/CLAUDE.md
```

## File Locations

| File | Purpose |
|------|---------|
| `/opt/llm-context/generate-context.sh` | Main generation script |
| `/opt/llm-context/run-context-generator.sh` | Auto-run wrapper |
| `~/.workbench/CLAUDE.md` | Generated context (primary) |
| `~/CLAUDE.md` | Symlink for auto-discovery |
| `~/.workbench/skills/` | Skill files (e.g., CUSTOM_APP.md) |

## Notes

- This feature requires the Workbench CLI (`wb`) to be installed
- `jq` is automatically installed if not present
- Context is only generated if a workspace is set (`wb workspace describe` succeeds)

---

_Note: This feature is automatically configured to work with the `wb-mcp-server` feature if both are installed._
