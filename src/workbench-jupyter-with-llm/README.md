
# Workbench Jupyter with LLM tools

Workbench JupyterLab with integrated AI assistance through Gemini CLI, Claude CLI, and MCP server support for enhanced development capabilities.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| containerImage | The container image to use | string | debian:bullseye |
| containerPort | The port to expose the container on | number | 8888 |



## Features

This template includes the following integrated features:

- **Workbench Tools** - Common bioinformatics and genomics tools
- **Gemini CLI** - Google Gemini AI assistant with MCP support
- **Claude CLI** - Anthropic Claude AI assistant (from ghcr.io/anthropics/devcontainer-features/claude-code:1.0)
- **WB MCP Server** - Workbench Model Context Protocol server for AI tool integration with workspace context

All AI assistants are pre-configured to work with the Workbench MCP server for enhanced workspace awareness.

---

_Note: This file was auto-generated from the [devcontainer-template.json](devcontainer-template.json).  Add additional notes to a `NOTES.md`._
