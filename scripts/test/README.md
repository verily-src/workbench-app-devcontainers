# Script tests

Run from the repository root. Requires Bats, Node.js and jq; integration tests
also require Docker with Compose.

```bash
npm ci --prefix startupscript/butane
bats scripts/test/parse-devcontainer.bats scripts/test/devcontainer.bats

docker pull python:3.12-alpine
docker build -t workbench-parser-test -f scripts/test/integration/parse-devcontainer.Dockerfile scripts/test/integration
bats scripts/test/integration
```

- `parse-devcontainer.bats`: migration from state files without a memory limit,
  plus failed container lookups/removals and retries without losing saved state.
- `devcontainer.bats`: stale setup markers, failed startup/snapshot/restore retries,
  and non-airlocked configs ignoring snapshots in either supported config location.
- `integration/devcontainer.bats`: repeated offline restoration of the same initial
  snapshot, preserving setup-time packages, the running browser, home data, and
  startup hooks while discarding later writable-layer changes; home bind
  initialization through Jupyter's host hook, ownership, and exclusion from snapshots;
  read-only completion markers and standard-app startup/recreation.
- `integration/parse-devcontainer.bats`: runs the complete parser in Linux against
  the Jupyter, RStudio, and regular R templates. Covers first creation, unchanged
  restarts, independent hardware changes, GPU removal, invalid and fallback shared
  memory, unset memory limits, workspace path normalization, and skipping prefetch
  only for airlocked snapshots. Also validates first-boot Compose overrides and
  runtime mounts/images. Docker and cloud metadata are mocked; the parser runs
  without network access.

Integration tests use isolated container/image names and clean up their own
resources. Missing feature sources and a broken build file catch accidental
feature installation or rebuilding during restore. Physical GPU transitions
still require a GPU VM.

Scaffolding tests create and remove `src/test-app`; run them in a disposable
checkout:

```bash
bats scripts/test/create-custom-app.bats
```

Use Bats `--filter` to run a single case. CI runs all unit and integration tests.
