# Cohort Studio in a Virtual Browser (virtual-browser-cohort-studio)

Serves [Cohort Studio](../cohort-studio) through a server-side Chromium session streamed to your
browser as pixels. Data stays in the VM: your laptop receives only video frames, never the app's
HTML, API responses or files. Shares the browser front end with `virtual-browser-jupyter` and
`virtual-browser-rstudio` (see `../browser-common`).

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | Cloud provider (gcp or aws) | string | aws |
| login | Whether to log in to workbench CLI | string | true |

## How it works

```text
your browser
  -> Workbench proxy
  -> browser:3000            Selkies HTTP/WebSocket stream, on app-network + backend-network
  -> Chromium --kiosk        managed policy: only application-server:8080 allowed
  -> http://application-server:8080   Cohort Studio (FastAPI + React, /api, /mcp),
                                      on backend-network only, no published ports
```

- `browser` — Chromium rendered by [Selkies](https://github.com/selkies-project) on port `3000`.
  Its `com.verily.workbench.proxy-target: "true"` label selects it for proxy traffic.
- `application-server` (Compose service `app`) — the unchanged Cohort Studio image, built from
  `../cohort-studio`. Same runtime config as plain Cohort Studio: runs as root, `/root` on the
  `work` volume, bucket mounts, and self-update from the `cohort-dashboard` branch on every start.

## Security properties

- The browser can open only `application-server:8080`. All other URLs are blocked.
- Downloads, file dialogs, printing, devtools, extensions and pop-ups are off.
- Clipboard is paste-in only. Text can't be copied out of the session.
- File transfer is upload-only, through the Selkies sidebar. Uploads land in
  `/root/browser-uploads` in the app container.
- The app has no published port and is not on `app-network`, so the Workbench proxy and other
  containers on that network can't reach it directly. The `backend-network` still has outbound
  internet access, which the app needs for BigQuery, AWS and self-update.

## Differences from plain Cohort Studio

- No file downloads to your laptop. CSV export and other download actions do nothing.
- The proxy port is `3000` (the browser), not `8080`.
- The MCP server at `/mcp` is not reachable from your laptop or through the proxy. Agents reach it
  only inside the VM:
  - in the app container: `docker exec -it application-server bash`, then `http://localhost:8080/mcp`;
  - from another container on the Compose `backend-network`: `http://application-server:8080/mcp`.

  Port 8080 is not published, so `localhost:8080` on the VM host does not work.
- Automatic clipboard paste needs clipboard access in your local browser. If it fails, paste into
  the sidebar's clipboard panel, click back into the app, and press Ctrl+V.

## Deploy

```sh
wb app config create \
  --name="Cohort Studio (isolated)" \
  --git-repo-url="https://github.com/verily-src/workbench-app-devcontainers.git" \
  --git-branch="cohort-dashboard" \
  --dev-container-path="src/virtual-browser-cohort-studio" \
  --description="Cohort Studio in a streamed, download-blocked browser"
```

Then create an app from this config in the workspace. Self-update keeps the backend on the head of
`cohort-dashboard`: restart the VM to deploy new commits. The build accepts `APP_SHA`; if no
commit SHA is supplied, the image reports `unknown` and self-update fetches the branch at startup.
Changes to the browser front end (`../browser-common`) or to this template need a new app.

## Configuring

Two values must match:

- `browser.build.args.APP_ORIGIN` in `docker-compose.build.yaml` — baked into the policy
  `URLAllowlist`.
- The `CHROME_CLI` URL in `docker-compose.yaml` — the page Chromium opens.

Both use `application-server:8080`. Do not use the hostname `app`: it is HSTS-preloaded in
Chromium and forces HTTPS against the HTTP backend.

The Workbench proxy targets the browser container on port `3000`. It must pass the Selkies
WebSocket upgrade used for the stream. The app has no separate login or auth-header contract;
Workbench access control applies at the proxy. The browser-to-app leg uses plain HTTP on the
private Compose network.
