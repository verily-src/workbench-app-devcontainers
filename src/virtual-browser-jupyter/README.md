
# JupyterLab in a Virtual Browser (virtual-browser-jupyter)

A template that serves JupyterLab through a streamed Chromium browser session.

## Options

| Options Id | Description | Type | Default Value |
|-----|-----|-----|-----|
| cloud | VM cloud environment | string | gcp |
| login | Whether to log in to workbench CLI | string | false |
| shmSize | Shared memory size for the application-server container | string | 64m |
| memoryLimit | Memory limit for the application-server container | string | 8192m |

## How it works

This template runs two containers on a shared Docker network:

- `application-server` — a Chromium browser rendered by
  [Selkies](https://github.com/selkies-project) and streamed to your local browser as pixels. This
  is the container that is published and proxied, on port `3000`.
- `jupyterlab` — the JupyterLab server. It listens on port `8888` on the internal `app-network`
  only and is not published to the host.

When you open the app you are looking at a video stream of Chromium running on the VM. Chromium
starts in application mode pointed at `http://jupyterlab:8888`, so there is no tab strip and no
address bar — the JupyterLab UI fills the window.

## Browser features not available in this template

Chromium in this template runs with a managed enterprise policy, `policies/managed-policy.json`,
which is baked into the browser image. The following browser features are turned off:

- Downloading files and "export to local" style save actions
- File open/save dialogs and local file system access from the page
- Copying clipboard contents out of the streamed session
- Printing (including print-to-PDF and cloud print)
- Browser developer tools and the JavaScript console
- Installing browser extensions
- Opening new tabs or windows, pop-ups, and navigating to sites other than JupyterLab
- Incognito and guest windows, additional browser profiles
- Password manager, autofill, translation, and site notifications

Pasting text into the session, uploading files through the Selkies sidebar, and everything inside
JupyterLab itself (notebooks, terminals, the file browser) work as usual.

## Working in the environment

Package installation works normally. From a notebook cell or a JupyterLab terminal you can use the
usual tooling, for example:

```bash
pip install <package>
conda install -c conda-forge <package>
Rscript -e 'install.packages("<package>")'
```

These run inside the `jupyterlab` container and are unaffected by the browser policy, which
applies only to Chromium.

## Configuring the template

Two values must agree with each other. If you point the browser at a different app, update both:

1. `CHROME_CLI` in `docker-compose.yaml` — the `--app=<url>` flag sets the URL Chromium opens:

   ```yaml
   CHROME_CLI: "--app=http://jupyterlab:8888 --force-app-mode --start-fullscreen ..."
   ```

2. `URLAllowlist` in `policies/managed-policy.json` — the allowlist must cover that same URL:

   ```json
   "URLAllowlist": ["http://jupyterlab:8888"]
   ```

`URLBlocklist` is `["*"]`, so a URL that is not in `URLAllowlist` will not load.

Other knobs:

- `shmSize` and `memoryLimit` template options apply to the browser container. Chromium needs
  shared memory to render; raise `shmSize` if you see renderer crashes.
- `initial_bookmarks.html` seeds the browser's bookmark bar.
- Selkies UI behavior (sidebar, file transfers, title) is controlled by the `SELKIES_*` environment
  variables in `docker-compose.yaml`.

## Building and running locally

From this directory:

```bash
# The app-network is declared external, so create it once.
docker network create app-network

# Substitute the template options, which are normally filled in on the VM.
sed -e 's|${templateOption:shmSize}|2g|' \
    -e 's|${templateOption:memoryLimit}|8192m|' \
    docker-compose.yaml > /tmp/docker-compose.local.yaml

docker compose -f /tmp/docker-compose.local.yaml build
docker compose -f /tmp/docker-compose.local.yaml up
```

Then open <http://localhost:3000>.

To confirm the policy landed in the image:

```bash
docker compose -f /tmp/docker-compose.local.yaml exec app \
  cat /etc/chromium/policies/managed/workbench-rbi.json
```

The active policy can also be inspected from within the session at `chrome://policy`.
