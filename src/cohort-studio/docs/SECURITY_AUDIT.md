# Cohort Studio security audit

2026-10-21. Scoped, read-only source review of the current dirty worktree on `cohort-dashboard` (HEAD `ca541aa`). This is **partial** coverage. No live Workbench, Aurora, S3, BigQuery, model, or browser endpoint was probed. No application code was changed. The active SynPUF export and import were not touched.

## Verdict

No exploitable boundary failure is confirmed by this pass. Two source-grounded leads need a bounded local test, and access-control impact depends on the deployed Workbench proxy. Do not treat this report as a clean bill of health or a completed Cloudflare six-phase audit.

## Leads that need validation

### A1. SPA file path may escape the static directory

- **Source:** [`app/main.py:1097`](../app/main.py#L1097) to [`app/main.py:1107`](../app/main.py#L1107). The catch-all route joins caller-controlled `path` to `STATIC_DIR`, tests only `is_file()`, then returns `FileResponse`. Starlette's installed `PathConvertor` accepts `.*` without a path-segment check.
- **Boundary and impact:** If the HTTP stack passes a decoded `..` segment to this route, a caller can request a readable file outside `static`. The app's default key store is `app/studio_config.json` ([`app/config.py:6`](../app/config.py#L6), [`app/config.py:145`](../app/config.py#L145)). Reading that file would disclose saved model keys and MCP tokens. Actual secret presence and proxy path normalization are not verified.
- **Preconditions:** A static build is present; the request reaches the backend catch-all with traversal segments; the target file is readable. Direct access from outside Workbench also depends on deployment routing.
- **Safe validation:** In a network-disabled, resource-limited copy with only dummy files, issue an ASGI request whose path has a decoded traversal segment and inspect the returned bytes. Test the Workbench proxy path handling separately with a harmless sentinel file. No real secret file is needed.
- **Fix:** Resolve the requested file, require it to be inside the resolved static root, and serve only an allowlisted set of frontend assets. Return the SPA index for other paths.
- **Status:** Needs validation. Source shows the unsafe join; no HTTP outcome was executed under the audit skill's required sandbox.

### A2. Catalog `SELECT` check does not confine reads to the selected S3 folder

- **Source:** [`app/main.py:332`](../app/main.py#L332) accepts custom view SQL. [`app/catalog.py:238`](../app/catalog.py#L238) checks only that DuckDB parses one `SELECT`; [`app/catalog.py:264`](../app/catalog.py#L264) creates a view from that SQL. [`app/catalog.py:102`](../app/catalog.py#L102) later queries the view. DuckDB is connected in the app container through [`app/duck.py:97`](../app/duck.py#L97).
- **Boundary and impact:** DuckDB `SELECT` can name table functions and data sources. If local file table functions are enabled, an API caller who can publish a catalog could make the backend read a local file such as the dummy equivalent of `studio_config.json` and return it through a catalog open. A remote source in the view might also use backend network or resource credentials. This would cross from folder-scoped data access to the app's file and network authority.
- **Preconditions:** The caller can reach catalog build, has a usable S3 resource for publication, and the DuckDB runtime allows the relevant table function at view creation and query time. These facts and the resulting bytes were not tested.
- **Safe validation:** With dummy local data and a stub S3 upload in an isolated sandbox, build a `SELECT` view over a harmless local sentinel and open it through the API. Verify DuckDB version, extension settings, and the final result.
- **Fix:** Do not accept arbitrary SQL for a folder-scoped catalog. Use typed view definitions that bind to files returned from the chosen folder, or run custom SQL in a separate process with no app secrets, no credential files, and explicit external-access restrictions.
- **Status:** Needs validation. The parser check is too broad as a policy, but this pass did not establish an end-to-end read.

### A3. Access control is external to the FastAPI app

- **Source:** [`app/main.py:230`](../app/main.py#L230) starts the self-update script; [`app/main.py:638`](../app/main.py#L638) starts exports; [`app/main.py:762`](../app/main.py#L762) changes model settings. These routes have no app-level identity check. The standard Compose template publishes port 8080 ([`docker-compose.yaml:12`](../docker-compose.yaml#L12)); the isolated-browser template places the backend on `backend-network` without a published port ([`../virtual-browser-cohort-studio/docker-compose.yaml:23`](../../virtual-browser-cohort-studio/docker-compose.yaml#L23)).
- **Boundary and impact:** If the deployed proxy or network admits an unintended caller, that caller receives the app container's Workbench authority and can trigger sensitive operations. This is a deployment-dependent access-control question, not a confirmed bypass.
- **Preconditions:** A path to the backend from an unintended principal. Actual Workbench ingress, identity forwarding, and authorization rules are outside this repository.
- **Safe validation:** Deployment owner checks ingress and proxy identity policy with a harmless endpoint and dummy principal; do not invoke update, export, or cloud operations.
- **Fix if exposed:** Restrict backend ingress to the authenticated proxy or isolated browser network and enforce user identity and authorization on sensitive API actions.
- **Status:** Needs validation. No claim of public exposure.

## Checks with no confirmed issue

- **SQL and saved recipes:** [`app/source_models.py:47`](../app/source_models.py#L47) uses typed, bounded source recipes; [`app/live_query.py:19`](../app/live_query.py#L19) quotes identifiers and binds filter values; [`app/queries.py:21`](../app/queries.py#L21) validates simple table names. I did not find a direct client-SQL path into Aurora joins or OMOP queries in the reviewed paths. This is not a proof for every query builder.
- **Exports and cache:** [`app/export_jobs.py:19`](../app/export_jobs.py#L19) sets job, byte, time, and concurrency limits; IDs are random; [`app/query_cache.py:96`](../app/query_cache.py#L96) includes resource, SQL, output, filters, and generation in the cache key. HTTP export ownership remains tied to the external access model in A3.
- **OMOP imports:** [`app/omop_load.py:181`](../app/omop_load.py#L181) requires a relative S3 path; [`app/omop_load.py:257`](../app/omop_load.py#L257) checks the schema name; table and column identifiers are quoted. The importer is a CLI operation, not an HTTP route. I did not read or run the active SynPUF job files.
- **Agent and MCP:** [`app/cohort_agent.py:80`](../app/cohort_agent.py#L80) binds tools to the selected resource, uses parsed cohort specs, and exposes aggregate/status tools. [`app/mcp_server.py:18`](../app/mcp_server.py#L18) offers read-oriented tools. The MCP route has no app-level identity boundary; the isolated template says it is reachable only on a private network. Prompt injection and live model behavior were not tested.
- **Self-update and sidecar:** [`app/self_update.sh:33`](../app/self_update.sh#L33) fetches a configured GitHub branch and builds it before activation; it does not verify a signature. GitHub branch control and Workbench ingress determine the real supply-chain risk. The sidecar's browser policy and proxy routing were not tested in a running instance.

## Method and limits

Read-only inspection of `main.py`, catalog, DuckDB, joins, source models, live query, query cache, export jobs, OMOP loader, agent/MCP tools, updater, and both Compose templates. No target-controlled test ran: the Cloudflare skill requires a network-disabled sandbox with an empty allowlisted environment, read-only target, isolated scratch, and resource limits; this workspace did not provide all controls to this audit. No prior Cloudflare coverage ledger or findings file was found or used. Independent hunter/verifier agents, machine-readable findings, and the skill's validators were not run, so the six-phase workflow remains incomplete.
