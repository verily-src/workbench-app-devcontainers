# Gemini CLI (gemini-cli)

Installs the Gemini CLI for AI-powered code assistance in your devcontainer.

## Example Usage

```json
"features": {
    "./.devcontainer/features/gemini-cli": {}
}
```

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| version | Version of Gemini CLI to install | string | latest |
| username | Username of the container user | string | root |
| userHomeDir | Home directory of the container user | string | /root |

## Requirements

This feature requires Node.js. If your devcontainer doesn't already have Node.js, add it:

```json
"features": {
    "ghcr.io/devcontainers/features/node": { "version": "lts" }
}
```

The `gemini-cli` feature will automatically install after Node.js via `installsAfter`.

---

_Note: This file was auto-generated from the [devcontainer-feature.json](devcontainer-feature.json).  Add additional notes to a `NOTES.md`._
