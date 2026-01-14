# Gemini CLI (gemini)

Installs Google Gemini CLI for AI assistance with MCP (Model Context Protocol) support.

## Example Usage

```json
"features": {
    "ghcr.io/verily-src/workbench-app-devcontainers/gemini:1": {}
}
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| version | Version of Gemini CLI to install | string | latest |
| username | Username of the container user | string | root |
| userHomeDir | Home directory of the container user | string | /root |

## Usage

After installation, the Gemini CLI will be available in your PATH. To use it:

1. Set your Gemini API key:
```bash
export GEMINI_API_KEY=your_api_key_here
```

2. Use the Gemini CLI:
```bash
gemini --help
```

## MCP Support

The Gemini CLI supports the Model Context Protocol (MCP) for integration with development tools. MCP servers can be added to enhance Gemini's capabilities with workspace-specific context.

To add an MCP server:
```bash
gemini mcp add <server-name> <command>
```

## Notes

- This feature only supports Debian-based systems (e.g., Ubuntu) on x86_64
- Node.js will be automatically installed if not present
- The Gemini CLI is installed globally via npm

---

_Note: This feature is automatically configured to work with the `wb-mcp-server` feature if both are installed._
