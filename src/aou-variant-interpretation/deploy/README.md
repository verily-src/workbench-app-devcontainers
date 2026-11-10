# deploy

Packaging for this app as a Verily Workbench custom app: a React +
TypeScript frontend (`ui/` at the repo root) served by a Java + Spring Boot
backend (`api/` at the repo root), built into a single container.

The `Dockerfile` here builds in two stages: it compiles the frontend with
Node, copies the built assets into the backend's static resources, then
builds the Spring Boot jar with Gradle. The resulting image runs the jar
directly, so the API and the frontend are both served from
port 8080 — no reverse proxy or CORS configuration needed.

This folder is a trimmed-down copy of the packaging conventions from
[verily-src/workbench-app-devcontainers](https://github.com/verily-src/workbench-app-devcontainers)
(the upstream repo also vendors dozens of unrelated app templates, shared
devcontainer features, and a test harness — none of that is used here).
`LICENSE` is the upstream repo's license, kept for attribution.

Note: `startupscript/` lives at the repository root, not here — see
[its README](../startupscript/README.md) for why.

## Configuration

- **Image**: pulled from `us-central1-docker.pkg.dev/dsp-artifact-registry/via/via:latest`,
  built by the [docker-build-push](../.github/workflows/docker-build-push.yml) workflow on
  merge to `main`. To test a branch before merging, run that workflow by hand (Actions >
  Build and push Docker image > Run workflow), which publishes the branch as `via:branch-<name>`
  (with `/` and other characters Docker tags disallow replaced by `-`) and `via:<sha>`; point
  `docker-compose.yaml` at the branch tag on that branch, and back at `:latest` before merging
- **Port**: 8080
- **User**: via (unprivileged; see [AoU exfiltration controls](#aou-exfiltration-controls))
- **Home Directory**: /home/via

## Access

Once deployed in Workbench, access the app at the app URL.

For local testing:
1. Create Docker network: `docker network create app-network`
2. From the repo root, pull and run:
   `SKIP_WORKBENCH_WAIT=true docker compose -f deploy/docker-compose.yaml up --no-deps app`.
   `WORKSPACE_CDR` and `GOOGLE_PROJECT` fall back to their defaults in `application.properties`
   when unset, with a warning in the container log. Without `SKIP_WORKBENCH_WAIT`, the container
   first waits up to 10 minutes for Workbench's environment. `--no-deps app` skips the
   `wondershaper` sidecar, which would otherwise try to throttle your own machine's network
   (it needs host networking and `NET_ADMIN`, and only makes sense on a Workbench VM).
3. Access at: `http://localhost:8080`

## Files

- `Dockerfile` - Multi-stage build combining `ui/` and `api/` into one image, run as the
  unprivileged `via` user
- `.devcontainer.json` - Devcontainer configuration. Deliberately has no `features`: the
  devcontainer CLI would build them into a new image on the VM at every boot, and the app
  needs nothing they provide. `runServices` lists the `wondershaper` sidecar alongside `app`
  so `devcontainer up` starts both
- `docker-compose.yaml` - Docker Compose configuration: the `app` service plus the
  `wondershaper` egress limiter
- `devcontainer-template.json` - Template options and metadata
- `entrypoint.sh` - Waits for Workbench-specific env vars, and checks the required ones are set, before starting the jar
- `LICENSE` - Upstream license (see above)

## Boot time

The container's startup is deliberately minimal: `startupscript/post-startup.sh` only
installs the Workbench CLI, logs in, and records the workspace's user email and project
for the app. Git setup, bucket mounting and devcontainer features from the upstream
template are left out because the app doesn't use them and each cost boot time. The
script's output is written to `/home/via/.workbench/post-startup-output.txt` inside the
container, which is the place to look when a boot is slow.

## AoU exfiltration controls

The All of Us Researcher Workbench requires its apps to limit data exfiltration the same
way the upstream AoU templates do
([r-analysis-aou](https://github.com/verily-src/workbench-app-devcontainers/tree/master/src/r-analysis-aou),
`jupyter-aou`, `aou-sas`). VIA applies the two controls that are relevant to an app
container nobody opens a shell in:

- **Egress rate limiting (`wondershaper`)**: `docker-compose.yaml` runs the same
  `app-wondershaper` sidecar image the upstream templates use, pinned by digest. It runs
  [wondershaper](https://github.com/magnific0/wondershaper) with host networking and
  `NET_ADMIN`, which caps the *whole VM's* upload bandwidth (the image's default is
  16 Mbit/s), so the limit covers this container's traffic without the app container
  itself needing any extra capability. `.devcontainer.json`'s `runServices` makes
  `devcontainer up` start it, and `app` has `depends_on: wondershaper` so the limiter
  starts first and the app does not start at all if the limiter can't (fail closed).

  One caveat, inherited from the sidecar: its entrypoint exempts
  `restricted.googleapis.com` (199.36.153.4/30) from the cap, and Workbench DNS maps
  every `*.googleapis.com` name to that range. So **Google API traffic -- BigQuery,
  GCS -- is not rate-limited**; the sidecar's comment says the VPC Service Controls
  perimeter is the control for that traffic, since it blocks cross-perimeter transfer
  outright. Everything else leaving the container is capped. Measured on a Workbench
  VM: an upload to GCS via the restricted endpoint ran at ~570 Mbit/s, the same upload
  pinned to a public Google address ran at 14.7 Mbit/s.
- **No root for the app user**: the image creates an unprivileged `via` user
  (`/home/via`, no sudoers entry) and runs the jar as that user via `USER via`. This is the
  equivalent of the upstream template's `rm /etc/sudoers.d/rstudio`. `sudo` stays
  installed only because `post-startup.sh` -- which the devcontainer CLI runs as root
  (`remoteUser`) -- uses `sudo -u via` to drop *down* to the app user for the Workbench CLI
  login; `via` itself cannot escalate. Everything the app needs (port 8080, read-only
  `/app/app.jar`, `/tmp`, the GCE metadata server for credentials) works without root.

Not applied, and why:

- The upstream templates' `aou-policy-interceptor.js` (a download/upload policy
  affirmation modal injected into RStudio) has no equivalent here: VIA's UI has no
  download, export or file-upload paths.
- The upstream `load-envs` helper resolves the AoU CDR version from the workspace's data
  collection. VIA reads `WORKSPACE_CDR` from the VM environment instead (see
  `docker-compose.yaml`).

After changing the user, the custom app's registration in the Workbench UI (its "default
user" and "home directory" fields) should say `via` and `/home/via`, matching what
`.devcontainer.json` passes to `post-startup.sh`.

## Usage

In Workbench UI, create a custom app pointing to this repository,
branch `main`, and folder `deploy`
