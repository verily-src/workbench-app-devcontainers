# VM startup scripts

These scripts set up Dev Container apps on Workbench VMs.

`050-parse-devcontainer.sh` renders the templates and tracks GPU, shared-memory,
and memory-limit changes for every app using the existing `container-state` file.
Apps without AIRLOCK_ENABLED use their existing delete-and-recreate flow for any
of these changes.
The parser skips OCI feature prefetching when an airlocked app already has its
initial snapshot; first creation and other apps retain feature prefetching.

Only virtual-browser Jupyter and RStudio set
`customizations.workbench.AIRLOCK_ENABLED: true`. After their first successful
`devcontainer up`, the host wrapper commits the initialized backend to
`workbench-local-snapshot:devcontainer`. Later recreations always reuse that image;
they never replace it with a new snapshot.

On hardware changes, the parser removes only the backend, then returns
to the existing build/up steps. `application-server`
stays running. The backend is identified by its devcontainer label, so JupyterLab
and RStudio can keep their existing container names. Ordinary restarts reuse the
existing containers.

GPU configuration targets the backend service named in `.devcontainer.json`.
The memory-limit and shared-memory placeholders appear only in that service's
Compose section, so rendering hardware changes leaves Chromium's settings alone.
The browser keeps the container name `application-server`: proxy startup inspects
that name to find its published port, and readiness checks use it too.

## Initial snapshot and restoration

First boot loads `docker-compose.build.yaml` for the original images and build
instructions. Once `devcontainer up` finishes setup and startup hooks, the wrapper
records setup completion on the host and commits the running backend. The commit
runs in the foreground: startup succeeds only if it finishes successfully. Docker
pauses the backend during the commit; the browser stays running.

Subsequent build/up calls inspect the local snapshot image. When it exists for an
airlocked app, the wrapper selects `docker-compose.yaml`, sets `runServices` to only
the backend, and omits first-boot build files and feature installation from
`.devcontainer.json`. It retains the Workbench customizations to identify airlocked
apps on later calls. No separate snapshot-ready file is needed.

The existing build step skips rebuilding, and `devcontainer up` restores the
backend offline whenever it needs replacement. Startup hooks, including bucket
remounting, run normally. Selecting only the backend prevents Compose from
recreating the browser. The browser's `restart: always` policy starts the existing
container when the VM boots.

The initial snapshot preserves setup-time packages and files. Changes made later
in the backend's writable layer are lost on recreation. Store persistent work in
mounted directories: Jupyter's `/home/jupyter` binds to
`/home/core/container-state.d/jupyter-home` through a local-driver volume that seeds
the image's home files and ownership on first use. Jupyter's own Compose file
defines this path, and its devcontainer `initializeCommand` creates the host
directory before initial startup. RStudio retains its named home
volume. Home data and other mounted volumes are excluded from snapshots and
survive recreation. The browser keeps its existing container and writable layer.

The host records successful setup in `container-state.d/setup/post-create.done`.
The backend mounts only this setup directory at `/var/lib/workbench/setup:ro`; its
`postCreateCommand` reads the marker to skip completed setup and never writes it.
A failed initial startup leaves the marker absent. Starting fresh without either
a backend or a snapshot clears any stale marker.

If the initial commit fails, setup completion remains recorded and the backend
stays running; the next `up` retries the commit. If restoration fails after removal,
the next build/up retries the same image without rebuilding.

Snapshots preserve the container entrypoint, command and metadata as-is. The CLI
adds its own startup wrapper during recreation. Keep one-time Workbench setup
inside the guarded post-create command; inherited feature hooks retain their
normal CLI behavior.

The existing Dev Container CLI and JSON-comment parser require Node.
Snapshot orchestration uses Bash, Docker and jq.
