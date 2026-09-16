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

- `application-server` — Chromium rendered by [Selkies](https://github.com/selkies-project) and
  streamed on port `3000`. This is the published, proxied container.
- `rstudio` — RStudio Server on `8787`, reachable only on the internal `app-network`.

Chromium runs in `--kiosk` mode pointed at `http://rstudio:8787` — fullscreen, no tab strip, address
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
values in `docker-compose.yaml`, two of which must match:

- `app.build.args.APP_ORIGIN` — baked into the policy `URLAllowlist`; the only origin the browser
  can reach.
- `CHROME_CLI` URL — the origin Chromium opens (`--kiosk … http://rstudio:8787`).

Both are `http://rstudio:8787` here. `URLBlocklist` is `["*"]`, so nothing else loads.
