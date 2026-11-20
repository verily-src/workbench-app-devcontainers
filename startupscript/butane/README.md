# VM startup scripts

These scripts set up Dev Container apps on Workbench VMs.

`050-parse-devcontainer.sh` renders the templates and tracks GPU, shared-memory,
and memory-limit changes for every app using the existing `container-state` file.
Apps without AIRLOCK_ENABLED use their existing delete-and-recreate flow for any
of these changes. The wrapper passes ordinary apps directly to the CLI without
creating Airlock setup or snapshot state.
The wrapper owns setup and snapshot handling; `060-start-proxy-agent.sh` resolves
the proxy target and starts an existing frontend before configuring the proxy.
The parser skips OCI feature prefetching when an airlocked app already has its
initial snapshot; first creation and other apps retain feature prefetching.

Only virtual-browser Jupyter and RStudio set
`customizations.workbench.AIRLOCK_ENABLED: true`. After their first successful
`devcontainer up`, the host wrapper commits the initialized backend to
`workbench-local-snapshot:devcontainer`. Later recreations always reuse that image;
they never replace it with a new snapshot.

On hardware changes, the parser removes only the app, then returns to the existing
build/up steps. The browser stays running. Ordinary restarts reuse both containers.

## Container roles

Apps use Compose service `app` and container name `application-server`.
Virtual-browser templates add `browser` for Chromium, which connects to the
backend through its `application-server` Docker DNS name.

Scripts identify the app by its fixed Docker container name, `application-server`.
Proxy traffic defaults to that app; an optional
`com.verily.workbench.proxy-target: "true"` label selects a frontend in the same
Compose project. Other devcontainers on the host, including apps created through
Playground, do not affect this lookup. Ordinary apps need no extra label. Readiness
checks both the app and frontend, along with proxy-agent.

GPU configuration targets the backend service named in `.devcontainer.json`.
The memory-limit and shared-memory placeholders appear only in that service's
Compose section, so rendering hardware changes leaves Chromium's settings alone.

## Initial snapshot and restoration

First boot loads `docker-compose.build.yaml` for the original images and build
instructions. Once `devcontainer up` finishes setup and startup hooks, the wrapper
records setup completion on the host and commits the running backend. The commit
runs in the foreground: startup succeeds only if it finishes successfully. Docker
pauses the backend during the commit; the browser stays running.

On subsequent startups, the wrapper checks for the local snapshot image. When it
exists for an airlocked app, the wrapper selects `docker-compose.yaml`, sets
`runServices` to only the backend, and omits first-boot build files and feature installation from
`.devcontainer.json`. It retains the Workbench customizations to identify airlocked
apps on later calls. No separate snapshot-ready file is needed.

The existing build step skips rebuilding, and `devcontainer up` restores the
backend offline whenever it needs replacement. Startup hooks, including bucket
remounting, run normally. Selecting only the backend prevents Compose from
recreating the browser. The browser's `restart: always` policy starts the existing
container when the VM boots.
The proxy startup script also starts the selected frontend if stopped, without
recreating it or changing the backend's lifecycle.

The initial snapshot preserves setup-time packages and files. Changes made later
in the backend's writable layer are lost on recreation. Store persistent work in
mounted directories: Jupyter's `/home/jupyter` uses the `jupyter-home` named volume,
and RStudio's `/home/rstudio` uses the `work` named volume. Docker seeds each empty
volume from the image's home files and ownership on first use.
Home data and other mounted volumes are excluded from snapshots and
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

## Share-enabled VMs

WSM tags VMs whose apps can be shared with the GCE network tag
`share-enabled-app` and runs them as the workspace's read-only
`shared-apps-reader` service account. `is_share_enabled_vm` in
`gcp/metadata-utils.sh` reads the tag from the metadata server and reports
unreadable tags as unknown. EC2 instances are never share-enabled.

On share-enabled VMs, `060-start-proxy-agent.sh` points the agent's `--host` at the
proxy target's IPv4 address on `app-network` and the container side of its first
published port, read with `docker inspect`. The agent runs on the host network, so
it reaches any port the container listens on over the bridge, and a request's
`X-App-Port` goes to that port on the container, never on the VM. Shared ports
need no publishing, but the app must listen on the container's interface
(`0.0.0.0`), not only on loopback. The script doesn't start the agent if the
address is missing, loopback or link-local, if no port is published, or if the
proxy target is a separate frontend such as the virtual browser. It reruns on
every boot and Docker restart, which picks up a changed address. Other VMs keep
`localhost` and the published host port. On any VM, the script doesn't start the
agent while the tags can't be read; systemd reruns the unit until they can.

`035-register-key.sh` retries a 403 from `registerKey` for about two minutes on
share-enabled VMs, since WSM stores the VM's instance ID just after creating it.
Other statuses, other VMs, and VMs whose tags can't be read fail on the first
refusal as before.
