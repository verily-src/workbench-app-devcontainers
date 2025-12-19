# Workbench MCP Server Feature

This dev container feature installs a local MCP (Model Context Protocol) server that wraps the Workbench CLI (`wb`), enabling AI assistants like Claude and Gemini to interact with your Workbench environment.

## What is MCP?

The Model Context Protocol (MCP) is an open standard developed by Anthropic that allows AI assistants to securely connect to external tools and data sources. This feature creates a local MCP server that exposes Workbench CLI functionality to AI assistants.

## Features

- **Zero Authentication**: The MCP server runs locally and doesn't require authentication (assumes `wb` is already authenticated)
- **Full wb CLI Access**: Exposes common Workbench operations as MCP tools
- **Easy Integration**: Works with Claude CLI, Gemini CLI, and any other MCP-compatible client
- **Standalone Binary**: Compiled Go binary with no runtime dependencies

## Installation

Add this feature to your `.devcontainer.json`:

```json
{
  "features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/wb-mcp-server:1": {
      "username": "vscode",
      "userHomeDir": "/home/vscode"
    }
  }
}
```

Or use it locally:

```json
{
  "features": {
    "./features/src/wb-mcp-server": {
      "username": "vscode",
      "userHomeDir": "/home/vscode"
    }
  }
}
```

## Available Tools

The MCP server exposes the following tools:

1. **wb_status** - Get current workspace and server status
2. **wb_workspace_list** - List all Workbench workspaces
3. **wb_resource_list** - List resources in the current workspace
4. **wb_resource_describe** - Describe a specific resource
5. **wb_folder_tree** - Display folder structure as a tree
6. **wb_app_list** - List all applications in the workspace
7. **wb_app_describe** - Describe a specific application
8. **wb_execute** - Execute any custom wb command

## Usage with Claude CLI

1. After the feature is installed, the MCP server binary is available at `/opt/wb-mcp-server/wb-mcp-server`

2. Configure Claude CLI by editing `~/.config/claude/config.json`:

```json
{
  "mcpServers": {
    "wb": {
      "command": "/opt/wb-mcp-server/wb-mcp-server"
    }
  }
}
```

3. Start Claude CLI, and it will automatically connect to the MCP server:

```bash
claude
```

4. Claude can now interact with your Workbench environment:

```
You: List all my workspaces
Claude: [calls wb_workspace_list tool] Here are your workspaces...

You: What resources are in my current workspace?
Claude: [calls wb_resource_list tool] Here are the resources...
```

## Usage with Gemini CLI

Configure the Gemini CLI similarly by adding the MCP server to its configuration file.

## Usage with Other MCP Clients

The server implements the standard MCP protocol over stdio. Any MCP-compatible client can connect by running:

```bash
/opt/wb-mcp-server/wb-mcp-server
```

The server reads JSON-RPC requests from stdin and writes responses to stdout.

## Manual Testing

You can test the server manually:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | /opt/wb-mcp-server/wb-mcp-server
```

## Environment Variables

After installation, these environment variables are available:

- `WB_MCP_SERVER_BIN`: Path to the MCP server binary
- `WB_MCP_CONFIG`: Path to the example MCP configuration file

## Prerequisites

- The `wb` CLI must be installed and authenticated in the container
- The user running the MCP server must have access to `wb` commands

## Options

- **username** (default: `root`): Container user that will run the MCP server
- **userHomeDir** (default: `/root`): Home directory of the container user
- **port** (default: `3000`): Reserved for future use (currently stdio-based)

## Security Notes

- This MCP server is designed for **local use only**
- It does not implement authentication (relies on local `wb` authentication)
- Do not expose this server to untrusted networks
- The server runs with the same permissions as the user who starts it

## Troubleshooting

### Server not found

Make sure the feature is installed and the binary exists:

```bash
ls -l /opt/wb-mcp-server/wb-mcp-server
```

### wb command not found

Ensure the Workbench CLI is installed and authenticated:

```bash
wb status
```

### Permission denied

Check that the binary is executable:

```bash
chmod +x /opt/wb-mcp-server/wb-mcp-server
```

## Development

The MCP server is written in Go and built during feature installation. Source code:

- `main.go`: Server implementation
- `go.mod`: Go module definition
- `install.sh`: Installation script

To modify the server, edit `main.go` and rebuild your dev container.
