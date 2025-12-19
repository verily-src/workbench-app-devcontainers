# VS Code App with Workbench MCP Server

This VS Code app now includes the **Workbench MCP Server**, which allows AI assistants like Claude CLI and Gemini CLI to interact with your Workbench environment through the Model Context Protocol (MCP).

## What is the MCP Server?

The MCP (Model Context Protocol) server is a local service that wraps the Workbench CLI (`wb`) commands, exposing them as tools that AI assistants can use. This enables you to ask your AI assistant to perform Workbench operations on your behalf.

## After Container Starts

Once your container is running, the MCP server binary is installed at:
```
/opt/wb-mcp-server/wb-mcp-server
```

Environment variables are also set:
- `$WB_MCP_SERVER_BIN` - Path to the MCP server binary
- `$WB_MCP_CONFIG` - Path to example MCP configuration

## Using with Claude CLI

To connect Claude CLI to the MCP server:

1. Create Claude's configuration directory:
```bash
mkdir -p /config/.config/claude
```

2. Add the MCP server configuration:
```bash
cat > /config/.config/claude/config.json <<'EOF'
{
  "mcpServers": {
    "wb": {
      "command": "/opt/wb-mcp-server/wb-mcp-server"
    }
  }
}
EOF
```

3. Start Claude CLI (install if needed):
```bash
# Install Claude CLI if not already installed
npm install -g @anthropic-ai/claude-cli

# Start Claude
claude
```

4. Now you can ask Claude to interact with Workbench:
```
You: List all my workspaces
Claude: [uses wb_workspace_list tool] Here are your workspaces...

You: What resources are in my current workspace?
Claude: [uses wb_resource_list tool] I found these resources...
```

## Using with Gemini CLI

Configure Gemini CLI similarly by adding the MCP server to its configuration file. Check Gemini CLI documentation for the exact configuration format.

## Available MCP Tools

The server provides these tools to AI assistants:

1. **wb_status** - Get current workspace and server status
2. **wb_workspace_list** - List all workspaces
3. **wb_resource_list** - List resources in workspace
4. **wb_resource_describe** - Describe a specific resource
5. **wb_folder_tree** - Display folder structure
6. **wb_app_list** - List applications
7. **wb_app_describe** - Describe an application
8. **wb_execute** - Execute any custom wb command

## Example Usage

Ask your AI assistant natural language questions:

- "Show me my Workbench status"
- "List all BigQuery datasets in my workspace"
- "Create a new folder called 'analysis-results'"
- "What applications are running?"
- "Describe the clinical-data dataset"

The AI will automatically call the appropriate wb commands through the MCP server.

## Prerequisites

- The `wb` CLI must be installed and authenticated
- The MCP server runs with the same permissions as the user (abc)
- This is designed for local use only (no network exposure)

## Manual Testing

Test the MCP server directly:

```bash
# Initialize the server
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | $WB_MCP_SERVER_BIN

# List available tools
echo '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | $WB_MCP_SERVER_BIN
```

## Troubleshooting

### Server not found
```bash
ls -l /opt/wb-mcp-server/wb-mcp-server
```

### wb not authenticated
```bash
wb auth status
wb auth login
```

### Permission issues
```bash
chmod +x /opt/wb-mcp-server/wb-mcp-server
```

## Security Notes

- The MCP server is for **local use only**
- It uses your existing wb authentication
- Do not expose to untrusted networks
- The server runs with your user permissions

## Learn More

- [MCP Protocol Documentation](https://modelcontextprotocol.io/)
- [Workbench CLI Reference](https://support.workbench.verily.com/docs/references/cli_reference/wb/)
- Feature source: `features/src/wb-mcp-server/`
