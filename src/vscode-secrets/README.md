
# Vscode with Secrets (vscode-secrets)

A Template to run vscode on workbench with WSM secret support.

This is a sample app demonstrating how to use the secret receiver to inject
secrets from Workspace Manager into a devcontainer. See `secrets.yml` for the
secret configuration and `docker-compose.yaml` for how the secret receiver
binary is built and injected as the container entrypoint.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |

---

_Note: This file was auto-generated from the [devcontainer-template.json](https://github.com/verily-src/workbench-app-devcontainers/blob/main/src/vscode-secrets/devcontainer-template.json).  Add additional notes to a `NOTES.md`._
