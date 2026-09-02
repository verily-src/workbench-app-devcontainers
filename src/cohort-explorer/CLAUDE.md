# CLAUDE.md — Cohort Explorer

Output tokens are precious. Be succinct. Use ASD-STE100 simplified technical english.
Write code to be as human readable as possible, not only sr-dev friendly.

## Vibe coding pitfalls

These are the top mistakes non-technical builders make when using AI to generate code. Since this
app is being built with heavy AI assistance, these are directly relevant.

1. **No upfront planning — letting the AI decide architecture.** Non-technical builders jump
   straight into prompting without defining data models, component boundaries, or API contracts.
   The AI fills every gap with its own assumptions, and those assumptions compound into an
   incoherent codebase. *Mitigation*: This plan exists for a reason. Follow it. Don't prompt
   "build me a cohort browser" — prompt for specific, scoped pieces that map to the plan.

2. **The entropy loop — patching patches until the code is incomprehensible.** A bug appears, you
   ask the AI to fix it, the fix breaks something else, you ask it to fix that, and now you're
   three layers deep in brittle code nobody understands. AI applies local fixes rather than
   systemic ones. *Mitigation*: Build incrementally. Commit at every working state. If a fix
   introduces a new bug, stop and understand the root cause before prompting again. Revert rather
   than stack patches.

3. **Accepting code you don't understand.** A Stanford study found developers using AI wrote less
   secure code while reporting higher confidence in its security. If you can't read the code, you
   can't debug, secure, or maintain it. *Mitigation*: Explain any non-obvious generated code
   before moving on. If a block of code isn't clear, ask for an explanation before accepting it.

## General newbie dev pitfalls

These are the top mistakes junior developers make on their first apps, regardless of AI
involvement.

1. **Over-engineering and premature complexity.** Using microservices, message queues, or
   elaborate design patterns for a simple CRUD app. *Mitigation*: Start with the simplest thing
   that works. This is a single-container FastAPI + React app on purpose. Don't add abstraction
   layers, service meshes, or caching until a concrete problem demands it.

2. **Feature creep / no MVP mindset.** Trying to build every feature before shipping.
   *Mitigation*: Step 1 is the MVP. It must be demonstrable to GNE before Step 2 begins. Resist
   the urge to pull Step 2 features forward.

3. **Skipping testing and error handling.** Relying on manual checks, swallowing exceptions
   silently, ignoring edge cases. *Mitigation*: Test each endpoint as it's built (`/docs` makes
   this easy with FastAPI). Handle errors explicitly — a visible error message is better than a
   silent failure. Don't ship an endpoint without verifying it works with real (or realistic
   mock) data.

## Debugging this app on a Workbench VM

Rules learned the hard way. Each one cost a full debug cycle.

**Read the state before you change it.** One `curl` or `docker exec ls` beats a rebuild. A rebuild
takes minutes, changes several things at once, and destroys the evidence. Never propose a rebuild
as a first diagnostic — only as a fix for a cause you have already named.

**Never use `docker compose up` / `docker compose build` on the VM.** The container is owned by the
devcontainer CLI. Plain compose skips the features (java, aws-cli, gcloud) and skips
`postCreateCommand`, so `/usr/bin/wb` is never installed and the app loses every `wb` call. Use
`sudo systemctl restart devcontainer.service`.

**`postCreateCommand` runs on container *creation*, not on start.** Restarting the devcontainer
service when the container still exists only runs `postStartCommand`, so `install-cli.sh` does not
re-run. To force the full startup path:

```bash
sudo docker rm -f application-server && sudo systemctl restart devcontainer.service
```

**A `.devcontainer.json` edit does not reach a running VM.** `040-git-clone-devcontainer.sh` skips
the clone when the repo is already present, and `prefetch-oci-features.sh` caches OCI features by
name, not digest. Committed changes land only on a new VM. Do not blame the most recent commit for
a runtime failure on an old VM — it never saw it.

**`/usr/local/bin/wb` in an error is never about this app.** `wb-path` defaults to
`/usr/local/bin/wb` and the CLI does not detect its own location, so `wb workspace configure-aws`
writes a path that exists nowhere. Check `wb config list` against `which wb`. The VM sets this in
`startupscript/aws/configure-aws-vault.sh`; do not paper over it by rewriting the generated config.

**On any proxy 404, try an incognito window first.** app-proxy renders an authorization failure as
`404 Not Found` on purpose, to avoid disclosing that a backend exists. A `ProxyAuth` cookie that is
present but stale sails past the `_login` redirect, and the proxy caches the resulting WSM rejection
under `wsm:<uuid>:<token>` for 60s, so reloading never escapes it. Rule out client state before you
inspect anything on the VM.

**Separate the app from the proxy before debugging a 404.** "Not Found" is FastAPI's default 404
body, and `main.py` only registers the SPA catch-all `if STATIC_DIR.exists()` — a missing
`/app/static` silently removes every non-`/api` route with nothing in the log. Tell the two apart
on the VM:

```bash
sudo curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/api/health   # backend alive?
sudo curl -s localhost:8080/ | head -c 100                                # HTML, or {"detail":"Not Found"}?
sudo docker exec application-server ls /app/static                        # did the frontend land?
```

HTML from `/` means the app is fine and the 404 is the app-proxy's.
