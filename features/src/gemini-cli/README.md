# Gemini CLI (gemini-cli)

Installs the Gemini CLI for AI-powered code assistance in your devcontainer.

## Example Usage

```json
"features": {
    "./.devcontainer/features/gemini-cli": {
        "username": "abc",
        "userHomeDir": "/config"
    }
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

## Authentication

After installation, users will need to authenticate with their Google Cloud account:

```bash
gcloud auth login
```

Or use service account credentials as needed for your Workbench setup.

---

_Note: This is a custom Workbench feature for Gemini CLI integration._
