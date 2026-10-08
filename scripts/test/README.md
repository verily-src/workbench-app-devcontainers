# Script tests

Run from the repository root. Requires Bats, Node.js and jq; integration tests
also require Docker with Compose.

```bash
npm ci --prefix startupscript/butane
bats scripts/test/parse-devcontainer.bats scripts/test/devcontainer.bats scripts/test/container-utils.bats

docker pull python:3.12-alpine
docker build -t workbench-parser-test -f scripts/test/integration/parse-devcontainer.Dockerfile scripts/test/integration
bats scripts/test/integration
```

- `parse-devcontainer.bats`: missing state keys, exact key matching, in-place
  memory limit updates, and failed Docker operations preserving saved state until
  a successful retry.
- `devcontainer.bats`: stale setup markers, failed startup/snapshot/restore retries,
  and ordinary apps ignoring snapshots and creating no Airlock state in either
  supported config location.
- `container-utils.bats`: default routing, project-scoped proxy overrides, invalid
  lookups, readiness requiring both the app and frontend, and metadata errors/overrides.
- `integration/devcontainer.bats`: repeated offline restoration of the same initial
  snapshot, preserving setup-time files, the running browser, home data, and
  startup hooks while discarding later writable-layer changes; named home volume
  initialization, ownership, and exclusion from snapshots;
  read-only completion markers, restoration leaving a renamed and stopped browser intact,
  and standard-app startup/recreation with other devcontainers on the host. The
  same lifecycle verifies that similar names and proxy labels in another Compose
  project do not interfere with app lookup.
- `integration/parse-devcontainer.bats`: runs the complete parser in Linux against
  the Jupyter, RStudio, and regular R templates. Covers first creation, unchanged
  restarts, independent hardware changes, in-place memory updates, GPU removal,
  invalid and fallback shared memory, unset memory limits, workspace path normalization, and skipping prefetch
  only for airlocked snapshots. Also validates first-boot Compose overrides and
  runtime mounts/images. Docker and cloud metadata are mocked; the parser runs
  without network access.
- `integration/startup-validation.bats`: mandatory proxy-start and readiness checks
  reject incomplete airlock setup or missing snapshots despite healthy containers;
  proxy startup starts the selected frontend before inspecting its port and stops
  on startup failure; ordinary apps retain their existing startup behavior.

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
The workflow also runs `tests/update-flatcar.bats` and the Linux-only
`tests/test-codeartifact.bats` suite.
