# opencode-harness

[OpenCode](https://opencode.ai) as a harness of the `agent-sandbox` feature: the agent runs in
the OpenShell sandbox, on the local model, with the Workbench tools the policy allows. Install
after `agent-sandbox`.

```json
"features": {
  "./.devcontainer/features/agent-sandbox": {"username": "abc", "userHomeDir": "/config"},
  "./.devcontainer/features/opencode-harness": {"username": "abc", "userHomeDir": "/config"}
}
```

| Option | Default | Meaning |
|---|---|---|
| `username`, `userHomeDir` | `root`, `/root` | The app user |
| `installLauncher` | `true` | Install the `opencode` command. `false` on the sandbox-broker, which needs only the harness files |

It installs, in `/opt/agent-sandbox/harnesses/`:

- `opencode.yaml`, the harness file: the image, the OpenCode binary, `opencode web` on port 4096.
- `opencode-config.sh`, the config hook: OpenCode's configuration with the served model, the
  `wb` MCP server with the denied tools turned off, and no sharing, updates or web fetches.

The `opencode` command always runs `agent-sandbox run`; there is no unsandboxed mode.

`sandbox/Dockerfile` is the sandbox image (OpenCode pinned, the Google client libraries, user
`sandbox`). A feature cannot build images, so the app's compose file does:

```yaml
sandbox-image:
  image: opencode-agent-sandbox:0.2
  build:
    context: .
    dockerfile: .devcontainer/features/opencode-harness/sandbox/Dockerfile
```

Tests: `python3 -m unittest discover -s tests/opencode-harness`.
