# Cohort Studio project state

Updated 2026-10-21. This is the shared project memory for Codex, Claude, Cursor, and OpenCode. Update this file after material changes. Record evidence, not assumptions.

## Active project

- Active app: `src/cohort-studio/` (React/TypeScript/Vite/ECharts + FastAPI).
- Branch: `cohort-dashboard`; base commit at start of this work: `5fc68f9`.
- The Panel app under `src/cohort-dashboard/` is superseded.
- Production storage is Aurora. DuckDB is the internal engine for loaded-frame analytics and cross-source joins. Do not add a standalone PostgreSQL deployment. Disposable PostgreSQL processes are local Aurora-compatibility test fixtures only.
- Use `uv` where available and Pydantic for API boundaries. Shared engine validation also applies to MCP and agent calls.
- See [README](../README.md), [architecture and decisions](architecture.md), [root agent rules](../../../AGENTS.md), and [agent next steps](AGENT_PLAN.md). Update architecture.md whenever a design decision changes.

## Verified delivery state

- `wb workspace describe` confirmed `bugbash-nextflowonaws`, UUID `5b932a68-43d4-432b-834c-9662e7dd0151`, server `dev-stable`, AWS environment `dev`.
- `wb app config list` confirmed **Cohort Studio** uses this repository, branch `cohort-dashboard`, and path `src/cohort-studio`.
- Latest `wb app list` reported **Cohort_Studio_EC2_MCP** stopped at [dev app](https://workbench-dev.verily.com/app/a54c0049-6905-46c3-93ad-2fe2973cf9b9/). The Oct 7 and Oct 20 Studio instances were also stopped. These are observations, not permanent state.
- Prior OMOP release: **`c911229deb8dcac409880ba114bba7e36c2d0501`** on `origin/cohort-dashboard`. The unrelated local `db.py` override and `.cursor/settings.json` are excluded. Its release snapshot with original db.py passed **294 tests in 27.90 s** before publication.
- The prior cleanup release kept the same in-app update path. Its isolated release snapshot, excluding unrelated local edits, passed **127 tests in 20.31 s**. Use the latest `cohort-dashboard` commit in `/api/version` to verify the running app; runtime verification is still pending.
- Deployment attempt: `wb app start --id=Cohort_Studio_EC2_MCP --workspace=bugbash-nextflowonaws` failed with `UnsupportedOperationException: Starting this type of app is not supported.` Start the AWS app through the Workbench UI. Its startup self-update should fetch the published branch; the in-app Update action is also available once running. Runtime SHA is **not verified**.
- Browser automation has no available browser in this session. `wb app update` only supports GCP in the installed CLI. The app's HTTP update endpoint is behind the Workbench browser proxy. No remote update was sent.
- The existing restart/update mechanism fetches the **pushed** branch. A local test pass does not update the dev instance.

## Join improvements (2026-10-21)

- Added full Aurora query scope for same-resource joins, explicit distinct entity counts, bounded durable join recipes, column settings, and a common join-key control.
- Live counts, filters, aggregates and numeric ranges cover the full source. Exports fetch the full filtered result and reject more than 100,000 rows. Compare, derive and dataset chat are disabled for live sources.
- Added a 30-second bounded in-memory Aurora Explore cache, visible freshness, manual refresh, and large-result warnings. Exports remain fresh and bypass the cache. Cache/warning validation passed in the final 146-test release snapshot.
- Source recipes use validated Pydantic models and survive saved-view reloads; no client SQL is accepted. Derived/uploaded frames are not durable sources.
- Final join/cache release snapshot passed **146 tests in 27.67 s**, excluding the unrelated local db.py override. Production frontend build and six new browser cases pass, including refresh cancellation and complete-upload versus capped-preview warnings. This validates local behavior, not live Aurora or Workbench deployment.
- Independent Codex CLI review (`gpt-6-luna`) found no remaining blocker after checking chart/filter contracts. OpenCode GLM max approved the join/settings scope after its initial defects were fixed. Codex and OpenCode GLM max also approved the cache scope; final browser/suite checks passed. See [review, evidence and next priorities](REVIEW_2026-10-21_JOINS.md).

## Implemented in this change

- OMOP backend supplied at handoff: schema/version detection, concept search, cohort SQL/count/attrition, person and domain opens, read-only MCP tools, Eunomia loader and fixtures.
- S3-to-Aurora CLI importer: Workbench S3 resource profile, relative ZIP key or CSV prefix, temporary staging, nested-file duplicate checks, and standalone OMOP header validation before schema changes. Fixed pooled connection ownership. Requires local staging disk; does not convert raw CMS claims or load Parquet/BigQuery.
- Source selection limit: detection chooses one CDM per Aurora resource. Several CDMs in the same database cannot be selected independently in the current UI. Use separate Aurora resources, or add explicit schema selection before supporting that layout.
- OMOP screen: choose resource, search concepts, OR concepts within a criterion, AND criteria, include/exclude, descendants, event minimum, dates, measurement values, strict before/after index, demographics, count/attrition, open people and clinical events.
- Cohort editor persists while switching tabs. Spec edits clear counts. Reopening a changed spec with the same name replaces its old tab.
- Strict Pydantic request validation rejects extra fields, wrong wrapper types, and blank agent messages. OMOP request errors return 400. Other API validation retains FastAPI's 422 behavior.
- Shared spec validation rejects falsey wrong types, non-YYYY-MM-DD dates, and nonfinite numbers. Lineage includes observation and vocabulary dependencies.
- Cohort assistant: resource-bound concept search, aggregate count, validated spec proposal, read-only workflow and app listing. New concept IDs must come from search or the current spec. Users review/apply proposals before Count/Open. No workflow/app mutation tools or person-row tool output.
- OpenRouter provider: server-side key via Settings or `OPENROUTER_API_KEY`; configurable model; existing compatible tool loop.
- Bedrock provider: Converse chat/tools, filter suggestion, connection test, configurable model/inference profile, AWS credential chain and `AWS_REGION`/`AWS_DEFAULT_REGION`. No stored Bedrock API key.
- Release hardening: image SHA defaults to `unknown` unless provided by build argument; updater locks concurrent runs, builds frontend and validates staged backend before activation, writes SHA last. Smoke checks cover frontend and version. Dependency installation and backend copy are still not fully atomic.

## Verification

- Current join/cache release: **146 passed in 27.67 s**, no skips, from an isolated copy with the unrelated db.py edit excluded. Frontend production build passed. Codex CLI (`gpt-6-luna`) and OpenCode GLM max approved the reviewed scope. See [review evidence](REVIEW_2026-10-21_JOINS.md).

- Prior cleanup suite: **127 passed in 19.74 s**. Standalone unit-test modules and direct helper checks were removed at user request. Browser/MCP HTTP flows, HTTP application outcomes, real database checks and updater subprocess tests remain. Shared database fixtures now live in conftest.py.
- Comment cleanup preserves runtime tool descriptions, CLI help, machine directives and vendor/legal text. Python executable AST and TypeScript emitted syntax were checked unchanged; the production frontend build passes. The unrelated db.py local override remains untouched.
- GLM max review of the test/fixture and comment cleanup found no blockers; 127 tests collected. Transcript: `/tmp/cohort-studio-e2e-review.jsonl`.
- The following 294-test results describe the previous published release, not the reduced current suite. Provider adapter unit tests were removed; live provider checks remain unverified.
- Full suite after GLM importer follow-up: **294 passed in 25.21 s**, via `uv`, including Chromium and a real temporary PostgreSQL instance. No skipped OMOP tests in this run. Earlier provider/UI review baseline was 275 tests.
- New importer tests cover real PostgreSQL nested-export loading, raw claims rejection before schema creation, failed replacement rollback preserving existing data, and pool connection lifetime. S3 download command tests use a mock transport; they do not verify live S3 permissions or Aurora access.
- Production frontend build and TypeScript checks pass. Vite still reports the existing large bundle warning.
- Browser→HTTP→PostgreSQL: GI bleed with diclofenac before index returns **14 / 100** fixture persons, matching a pandas reference; opens the cohort and clinical table; verifies changed same-name cohort replacement and stale-count invalidation.
- MCP streamable HTTP client: real search and count against the fixture database pass.
- Bedrock request shapes validated through a real Boto3 client with botocore Stubber. No live model calls.
- Update tests cover failed frontend build leaving the live app unchanged and successful staged activation. Docker image build/smoke was not run.
- Screenshot inspected: `/tmp/cohort-studio-omop.png` (local test artifact).
- OpenCode independent review: **GLM 5.3 Flash, max reasoning**, read-only, requested by user; complete. No verified release blocker or wrong-cohort result found. See [review and triage](REVIEW_2026-10-20.md). Earlier DeepSeek review was stopped when user selected GLM.

## Remaining limits / next steps

### Current requirements

- Load OMOP exports from Workbench S3 resources into Aurora. Support multiple sources; [CMS SynPUF](https://workbench.verily.com/data-collections/cms-syn-puf) is one user-supplied example. Its storage location and export format are not yet verified. Raw claims require a separate OMOP conversion.
- The [official Workbench guide](https://support.workbench.verily.com/docs/guides/research_data/gcp/work_with_omop_bigquery/) documents an OMOP SynPUF dataset in BigQuery (`bigquery-public-data.cms_synthetic_patient_data_omop`). This does not establish an S3 export for the supplied collection.
- A direct TCP check from this machine to the existing dev Aurora endpoint on port 5432 failed with `Network is unreachable` (2026-10-20). Run real import validation from the Workbench VM with resource credentials and VPC access. No cloud data was changed.
- Support the browser isolation sidecar, following `src/virtual-browser-jupyter` on master. This branch already has `src/virtual-browser-cohort-studio` and shared `src/browser-common`. The audit confirmed the same two-container routing. The isolated build now accepts `APP_SHA`; its smoke script checks Studio HTML, health and version before the existing browser/network checks. Shell syntax passes. Runtime validation is pending: this machine has neither a Docker daemon nor a Compose plugin. A local browser test alone does not verify Selkies or Workbench proxy routing.
- In the isolated template, the proxy reaches the browser on port 3000. The backend stays on `backend-network`, with no published port. S3 imports and model calls run on the backend. MCP clients must have private network access; do not expose port 8080 to bypass isolation.
- User clarified that release means the **in-app Update button**. It fetches pushed code and restarts the existing container, without recreating the Workbench app/VM. Do not substitute CLI app lifecycle actions for this flow.
- Jev assessment assumes TypeSafe's decision model. [Scope](JEV_SCOPE.md): optional future unified-assistant routing or ranking retrieved concepts, evaluated before use. No adapter is installed or invoked. Existing UI selection and SQL cohort logic remain authoritative.
- [Join branch comparison](JOIN_BRANCH_REVIEW.md) reviewed `yp-cohort-explorer-joins` at `4d25d21`. The five identified gaps are implemented in the current work: full-database exploration of joined sources, distinct entity counts, restored join recipes, schema overrides and an apply-to-all key picker. No Explorer stack was copied; Studio already has broader join semantics and cross-source support.

1. Preserve the concurrent db.py local-mode edit and Cursor settings outside the release. GLM follow-up fixes and final local checks are complete.
2. Branch publication is complete. Start/update `Cohort_Studio_EC2_MCP` through the UI, then verify `/api/version`, frontend, and real resource operations from inside the workspace. This installed CLI cannot start AWS apps.
3. Real Aurora and `omop_load --resource-id` are not verified. Do not load/replace clinical schemas without a specific target and instruction.
4. Full-size vocabulary search performance is unverified (ILIKE under timeout). Eunomia is a small synthetic fixture, not representative scale.
5. OpenRouter and Bedrock have no live inference test here. Bedrock needs approved model access, IAM permissions, Region, and network reachability; Workbench resource profiles do not prove Bedrock access.
6. AgentCore is **planned, not deployed or integrated**. Runtime ARN/role/network/identity details are pending. Workflow submission/cancellation and app start/stop/update through the agent are also planned, not implemented. See AGENT_PLAN.
7. OMOP definitions are not persisted in saved views; the builder is session state. Opened OMOP tabs have no generic table sourceRef and are excluded from generic saved-view persistence.

## Dev acceptance still required

1. Identify the added Workbench S3 resource, relative OMOP export path, and target Aurora resource/schema. Run the README importer command from the app container. Record source version and table counts.
2. Refresh OMOP detection, search a known concept, count a cohort, and open its people/events. Compare the count with direct Aurora SQL.
3. Start the isolated template from the tested commit. Run `tests/virtual-browser-cohort-studio.sh` with `EXPECTED_APP_SHA` set to that commit.
4. In the Workbench streamed browser, repeat concept search, count and open; verify the assistant and reconnect after a backend update. Confirm browser restrictions in the running Chromium session. Smoke checks of policy files alone do not prove enforcement.
5. Record the deployed commit, app URL, source/target resources and results here. No step above is complete merely because local tests passed.

## Change ledger

- 2026-10-20: Inspected current code and Claude session history. Latest two Claude sessions ended at usage limits. Older personal memory was stale; root AGENTS.md and CLAUDE.md now point here.
- 2026-10-20: Added OMOP UI and outcome tests, fixed spec validation/lineage, hardened update path.
- 2026-10-20: Added OpenRouter, Bedrock Converse, and specialized cohort assistant with workflow/app status tools. Used lower-cost subagents at user request.
- 2026-10-20: Adopted uv and Pydantic preferences. Full suite passed. GLM max external review completed; follow-up fixes and final checks are recorded in REVIEW_2026-10-20.md. Release not performed.
- 2026-10-20: Added generic S3-to-Aurora import CLI and hardened isolated-template build/smoke checks. Full suite passed (292). Recorded CMS SynPUF source ambiguity, failed Aurora network check, and missing Docker runtime. No cloud data load or release performed.
- 2026-10-21: Published code release c911229 after 294 tests on the release snapshot. CLI start failed for the AWS app; UI start/update and runtime verification remain. Browser-sidecar template changes require a new instance, not an in-app code update.
- 2026-10-21: Reduced the suite to outcome/boundary tests, removed ordinary code comments, refreshed architecture.md and its decision record, and scoped Jev without implementation. In-app Update is the requested code-release path.

### Concurrent work detected

After the first full test run, `app/db.py` gained `STUDIO_LOCAL_AURORA` support from an
unknown concurrent editor. This was not part of the assigned agent changes.
It is preserved and excluded from this release. No dedicated local-mode test
was added by this session. A separate release snapshot uses the original db.py.
