# JupyterLab in a Virtual Browser (virtual-browser-jupyter)

Serves JupyterLab through a server-side Chromium session streamed to your browser as pixels.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| shmSize | Shared memory size for the JupyterLab container | string | 64m |
| memoryLimit | Memory limit for the JupyterLab container | string | 8192m |

## How it works

Two containers on a shared network:

- `application-server` — Chromium rendered by [Selkies](https://github.com/selkies-project) and
  streamed on port `3000`. This is the published, proxied container.
- `jupyterlab` — the JupyterLab server on `8888`, reachable only on the internal `app-network`.

You see a video stream of Chromium running on the VM, started in `--kiosk` mode at
`http://jupyterlab:8888` — fullscreen, no tab strip, address bar, or window decorations, just the
JupyterLab UI. The Selkies control sidebar is hidden.

## What's not available

A managed Chromium policy (from the shared `browser-common` image, baked in at build) turns off:
downloads and export-to-local, file dialogs and file-system access, clipboard-out, printing,
devtools, extensions, new tabs / pop-ups / off-app navigation, incognito and extra profiles, and
password manager / autofill / translation / notifications.

Notebooks, terminals, and file editing work normally — but JupyterLab's own **Download** / export
commands rely on the disabled browser actions, so they won't save to your local machine. The Selkies
control sidebar is hidden.

## Configuring

The browser front end (Dockerfile, policy template, Selkies env) lives in `../browser-common`. This
template only supplies the JupyterLab-specific values in `docker-compose.yaml`, two of which must
match:

- `app.build.args.APP_ORIGIN` — baked into the policy `URLAllowlist`; the only origin the browser
  can reach.
- `CHROME_CLI` URL — the origin Chromium opens (`--kiosk … http://jupyterlab:8888`).

Both are `http://jupyterlab:8888` here. `URLBlocklist` is `["*"]`, so nothing else loads.

Other configs:

- `shmSize` / `memoryLimit` apply to the JupyterLab container.
- Shared Selkies defaults are `ENV` in the `browser-common` image; override any in this service's
  `environment`.
