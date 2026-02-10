# LLM Context Generator (llm-context)

A devcontainer feature that generates context files for LLMs (Claude Code, Gemini CLI, etc.) to understand the current Workbench workspace.

## What It Does

When installed, this feature:

1. **Generates `~/CLAUDE.md`** - A comprehensive context file that Claude Code auto-discovers
2. **Provides workspace context** - Current workspace, resources, workflows, and tools
3. **Includes skill files** - Detailed guides for specific tasks (e.g., creating custom apps)
4. **Sets up environment** - Aliases and variables for easy context regeneration

## Usage

### In a devcontainer.json

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/llm-context:latest": {
      "autorun": true
    }
  }
}
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `autorun` | boolean | `true` | Automatically generate context on container start |

### Manual Generation

```bash
# Generate/refresh context
generate-llm-context

# Or use the alias
refresh-context

# Or run directly
/opt/llm-context/generate-context.sh
```

## What Gets Generated

### ~/CLAUDE.md

Claude Code automatically reads `~/CLAUDE.md` on startup. This file includes:

- **Workspace info**: Name, ID, cloud platform, your role
- **Resource summary**: All resources with cloud paths
- **Quick reference JSON**: Machine-readable resource paths and environment variables
- **Data exploration commands**: How to query BigQuery, list GCS files
- **Best practices**: Data persistence, cost awareness, MCP vs CLI guidance
- **Skill references**: Links to detailed guides for specific tasks

### ~/.workbench/skills/

Detailed skill files for specific topics:

| Skill | File | Description |
|-------|------|-------------|
| Custom Apps | `CUSTOM_APP.md` | How to create Workbench custom apps |

## How Claude Code Discovers Context

1. Claude Code checks for `~/CLAUDE.md` on startup
2. If found, it reads the file and uses it as initial context
3. The file references skill files that Claude reads on-demand

## Dependencies

This feature depends on:

- **workbench-tools**: Provides the `wb` CLI for fetching workspace data
- **jq**: JSON processing (installed automatically if missing)

## Example Output

After running, you'll see:

```
==========================================
  Workbench LLM Context Generator
==========================================

[INFO] Checking prerequisites...
[INFO] Prerequisites OK
[INFO] Setting up directories...
[INFO] Installing skill files...
[INFO] Fetching workspace information...
[INFO] Fetching resources...
[INFO] Fetching workflows...
[INFO] Fetching apps...
[INFO] Generating CLAUDE.md...
[INFO] Created /home/jupyter/.workbench/CLAUDE.md
[INFO] Created symlink ~/CLAUDE.md → /home/jupyter/.workbench/CLAUDE.md

[INFO] Context generation complete!

Generated file:
  - /home/jupyter/.workbench/CLAUDE.md
  - ~/CLAUDE.md (symlink for auto-discovery)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Claude Code will automatically discover ~/CLAUDE.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Troubleshooting

### Context not generating?

1. Check if workspace is set: `wb workspace describe`
2. If not authenticated: `wb auth login --mode=APP_DEFAULT_CREDENTIALS`
3. Then set workspace: `wb workspace set <workspace-id>`

### Claude Code not seeing context?

1. Ensure `~/CLAUDE.md` exists: `ls -la ~/CLAUDE.md`
2. Check it's not empty: `head ~/CLAUDE.md`
3. Restart Claude Code to re-read the file

### Need to refresh after workspace changes?

```bash
refresh-context
```

## Integration with MCP Server

This feature works alongside the `wb-mcp-server` feature:

- **CLAUDE.md**: Provides static context (workspace info, how-to guides)
- **MCP Server**: Provides dynamic tools (list resources, run queries in real-time)

Together, they give LLMs full context AND active capabilities.
