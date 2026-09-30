# RStudio in a Virtual Browser (virtual-browser-rstudio)

Serves RStudio Server through a server-side Chromium session streamed to your browser as pixels.
Shares the browser front end with `virtual-browser-jupyter` (see `../browser-common`); only the
backend app differs.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| shmSize | Shared memory size for the RStudio container | string | 64m |
| memoryLimit | Memory limit for the RStudio container | string | 8192m |

## How it works

Two containers on a shared network:

- `browser` — Chromium rendered by [Selkies](https://github.com/selkies-project) and
  streamed on port `3000`. Its `com.verily.workbench.proxy-target: "true"` label
  selects it for proxy traffic.
- `application-server` (Compose service `app`) — RStudio Server on `8787`,
  reachable only on the internal `backend-network`.

Chromium runs in `--kiosk` mode pointed at `http://app:8787` — fullscreen, no tab strip, address
bar, or window decorations. The Selkies control sidebar is hidden.

## What's not available

The managed Chromium policy (from the shared `browser-common` image) turns off: downloads and
export-to-local, file dialogs and file-system access, clipboard-out, printing, devtools, extensions,
new tabs / pop-ups / off-app navigation, incognito and extra profiles, and password manager /
autofill / translation / notifications.

RStudio itself works normally, but its export/download actions rely on the disabled browser actions,
so they won't save to your local machine. The Selkies sidebar (including file upload) is hidden.

## Configuring

The browser front end lives in `../browser-common`. This template supplies only the RStudio-specific
values in `docker-compose.build.yaml` and `docker-compose.yaml`, two of which must match:

- `browser.build.args.APP_ORIGIN` — baked into the policy `URLAllowlist`; the only origin the browser
  can reach.
- `CHROME_CLI` URL — the origin Chromium opens (`--kiosk … http://app:8787`).

Both are `http://app:8787` here. `URLBlocklist` is `["*"]`, so nothing else loads.

### Hardware changes

After the first successful startup, RStudio is snapshotted once to
`workbench-local-snapshot:devcontainer`. GPU, shared-memory or memory-limit changes
recreate it from that initial snapshot with the new settings and existing named
volumes. The browser container stays running; a stopped browser is started without
recreation on restore. First boot also loads
`docker-compose.build.yaml`; later recreation needs no builds or image pulls.
Completed setup stays skipped and startup hooks run.

Packages installed during initial setup and files in the mounted home directory
survive. Later changes outside mounted directories are lost on recreation.

The VM host records setup completion and mounts the marker directory read-only in
the backend. See the [startup lifecycle](../../startupscript/butane/README.md) for details.
