# ttyd - Web-based Terminal

Installs [ttyd](https://github.com/tsl0922/ttyd), a simple command-line tool for sharing your terminal over the web.

## Usage

```json
"features": {
    "./.devcontainer/features/ttyd": {
        "version": "latest",
        "port": "7681"
    }
}
```

## Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| version | string | `latest` | Version of ttyd to install (e.g., '1.7.7' or 'latest') |
| port | string | `7681` | Port ttyd will listen on |

## Running ttyd

Configure ttyd as the container command in your `docker-compose.yaml`:

```yaml
services:
  app:
    command: ["ttyd", "-p", "7681", "bash"]
    ports:
      - 7681:7681
```

Then access the terminal in your browser at `http://localhost:7681`.

## Example

See the repository README for examples of using ttyd with Linux distributions that don't have a built-in UI.
