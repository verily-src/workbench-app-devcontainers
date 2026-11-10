# VS Code App for AoU (vscode-aou)

A template to run VS Code (code-server) on Workbench for AoU. Compared with `vscode`:

- A `wondershaper` sidecar limits the VM's network bandwidth to reduce the rate of
  data egress.
- The user has no sudo, and the Gemini and Claude extensions are not installed.
- An injected script shows an AoU policy reminder before files are uploaded or
  downloaded through the code-server UI (explorer menu, file picker, drag and drop).
  This is a reminder only, not enforcement.
- AoU environment variables are loaded from `~/load-env.sh` in terminals.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| shmSize | Shared memory size for the application-server container | string | 64m |
| memoryLimit | Memory limit for the application-server container | string | 8192m |
