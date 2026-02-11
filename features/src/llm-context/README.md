# LLM Context Generator (`llm-context`)

A devcontainer feature that generates `~/CLAUDE.md` for LLMs (Claude Code, Gemini CLI, etc.) with Workbench workspace context.

## What It Does

When installed, this feature:

1. **Generates `~/CLAUDE.md`** - Claude Code auto-discovers this file on startup
2. **Provides workspace context** - Name, ID, role, resources, cloud paths
3. **Includes skill files** - Detailed guides (e.g., custom app creation)
4. **Sets up aliases** - `generate-llm-context`, `refresh-context`

## Usage

### In `.devcontainer.json`

```json
{
  "features": {
    "ghcr.io/aculotti-verily/wb-app-mcp-and-context/llm-context:latest": {
      "username": "jupyter",
      "userHomeDir": "/home/jupyter"
    }
  }
}
```

Or for local development:

```json
{
  "features": {
    "./.devcontainer/features/llm-context": {
      "username": "jupyter",
      "userHomeDir": "/home/jupyter"
    }
  }
}
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `username` | string | `root` | Container user to install for |
| `userHomeDir` | string | auto | Home directory (auto-detected from username) |

## When Context Gets Generated

1. **On first terminal open** - Via `.bashrc` trigger (runs in background)
2. **Manually** - Run `generate-llm-context` or `refresh-context`

## What's in `~/CLAUDE.md`

- **Quick Rules** - When to use this file vs. MCP/CLI
- **Current Workspace** - Name, ID, description, role, cloud platform
- **Resource Paths** - JSON lookup for all resources
- **Data Persistence** - Warning + save commands
- **Data Exploration** - Common BigQuery/GCS commands
- **MCP Tools** - Available tools and CLI equivalents
- **Skills** - Links to detailed guides

## Dependencies

- **Workbench CLI (`wb`)** - Must be installed and authenticated
- **jq** - Installed automatically if missing

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
| `/opt/llm-context/generate-context.sh` | Main script |
| `~/.workbench/CLAUDE.md` | Generated context |
| `~/CLAUDE.md` | Symlink (for auto-discovery) |
| `~/.workbench/skills/` | Skill files |
