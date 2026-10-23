# Cohort Studio project state

Updated 2026-10-23. This is the shared project memory for Codex, Claude, Cursor, and OpenCode. Update this file after material changes. Record evidence, not assumptions.

## Active project

- Follow-up 2026-10-23: charts below cohort filters, chart/table result toggle,
  independent clinical-table opens, and aligned dataset toolbar implemented
  locally. Custom read-only Aurora SQL sources in the join builder are
  implemented, including preview, full-source joins and durable saved recipes.
  Final isolated suite: **216 passed in 72.93s**, including three real-container
  browser flows. OpenCode GLM max frontend/backend review and the independent
  security recheck found no remaining blocker after fixes. See [review](SQL_SOURCE_REVIEW.md). Workflow demo is scoped in
  [DEMO_WORKFLOW_SCOPE.md](DEMO_WORKFLOW_SCOPE.md); no job submitted. These
  follow-up changes are deployed at `ad62261`, verified below.

- Standing validation rule: always validate changes locally where possible before shipping or declaring them complete. Prefer local app/container E2E checks of the user outcome. Record results and limits; verify cloud-specific behavior in the live environment separately. This rule is also in root AGENTS.md, shared with Claude through CLAUDE.md.
- Next update scoped 2026-10-23: source selection inside the join builder,
  schema-first key discovery and optional Jev/TypeSafe ranking, with bounded
  local probes and user-applied recommendations. See [scope](JEV_SCOPE.md).
  Deployed and verified at `d7b01a8` on 2026-10-23. User also requires a
  simpler builder and real container/browser validation with local PostgreSQL
  as the Aurora substitute. Production storage remains Aurora.

- Primary product goal (user clarification): OMOP plus multimodal joins, built visually like BI tools, through a SQL editor, or by an isolated assistant; all routes create one reusable data model/cube. Logical model first, optional cached extract. SQL editor and isolated join agent are planned, not delivered.

- Active app: `src/cohort-studio/` (React/TypeScript/Vite/ECharts + FastAPI).
- Branch: `cohort-dashboard`; base commit at start of this work: `5fc68f9`.
- The Panel app under `src/cohort-dashboard/` is superseded.
- Production storage is Aurora. DuckDB is the internal engine for loaded-frame analytics and cross-source joins. Do not add a standalone PostgreSQL deployment. Disposable PostgreSQL processes are local Aurora-compatibility test fixtures only.
- Use `uv` where available and Pydantic for API boundaries. Shared engine validation also applies to MCP and agent calls.
- See [README](../README.md), [architecture and decisions](architecture.md), [root agent rules](../../../AGENTS.md), and [agent next steps](AGENT_PLAN.md). Update architecture.md whenever a design decision changes.

## Verified delivery state

- **2026-10-23 SQL/UI release deployed:** `ad62261767ed1c8d8c8074204c15d0e0fdc69429`
  on Cohort_Studio_EC2_MCP via the existing update endpoint. Update SSM
  `5202e26e-a9c9-4be8-ad39-807120ca318a`; live validation SSM
  `d0653e3f-d480-48ba-b48a-cfb33912843e` succeeded and verified version.
  Custom SQL preview returned 20 rows; opening selected 100 people with
  samples, joining genotypes returned 20,000 rows and matched independent
  SQL. Saved SQL join recipe reopened successfully. Preview request 14.28s,
  source open 1.92s, join 0.60s, live query 0.13s, reopen 0.78s. These are
  single-call timings, including request/setup costs, not a load benchmark.
  Test-created dataset handles were closed. Final isolated local suite:
  216 passed in 72.93s; final chart screenshot check also passed (4.89s).
  Browser validation was local; live validation used app HTTP APIs inside
  the Workbench container. Workflow demo remains scoped only.

- **2026-10-23 release deployed:** `d7b01a834bbc0853d72944f9f57e863f0dc93549`
  on Cohort_Studio_EC2_MCP through the existing in-app update endpoint.
  Update SSM `db6b18c5-4af0-4fb9-a77a-3e785c450bc8`; live checks
  `abb6457e-b588-4bec-8d05-0aab844a3f50` succeeded. Version verified.
  Live Aurora recommendations returned person_id, sample_id and variant_id
  in 0.41/0.05/0.06 seconds. Default summary: 90,085/100,000 persons in
  3.21 seconds; impossible-age cohort: zero in 0.45 seconds. Condition 75344
  cohort: 3,006 persons in 5.89 seconds, matching independent SQL. Gender
  and age totals matched membership. These are single-call timings, not a
  load benchmark. Browser checks were local; streamed Workbench browser
  isolation remains unverified. No materialized views or OMOP summary cache
  were added. TypeSafe remains unconfigured. Unrelated db.py and .cursor
  edits were preserved and excluded from release.

- 2026-10-23 source-first join update: source/schema/table picker can start from
  an empty workspace; key recommendations are explicit Apply actions, support
  composite foreign keys and later-step aliases, and retain manual joins.
  Optional Jev uses TypeSafe credentials plus an explicit model; schema and
  non-null flags only, no row values. No credential is set here, so live Jev
  inference remains unverified. Codex frontend and OpenCode GLM max backend
  reviews found no release blocker; review follow-ups were fixed.
  Isolated release snapshot with committed `db.py`: **190 passed in 57.86s**,
  no skips, including the real container browser flow. PostgreSQL 16 container
  flow selected four tables inside the builder, previewed/executed joins, and
  verified 2,000 rows, 100 people and 20 variants. Local stack is available at
  `http://127.0.0.1:8081` (Compose project `cohort-local-validation`). Workbench
  browser isolation and live Jev are not covered by this result. See
  [local validation](LOCAL_VALIDATION.md). User requested automatic OMOP charts
  after this work: cohort selections/filters should automatically build
  visualizations and use fixed OMOP relationships. Hardcoded behavior is
  authorized; TypeSafe credentials will be added later. This follow-up is implemented, with a visible Tables/OMOP toggle separate
  from database selection. Final release validation covered all 193 tests:
  191 passed in the full run; two old dropdown selectors failed and were
  corrected. All three OMOP browser flows then passed in 4.13s. Container
  build passed; real container joins and filter-driven charts passed. Chart
  bounds at 1280/900 and stale-response guards passed browser checks.
  OpenCode GLM max summary review found no blocker. Deployed as recorded below.

- AWS access check 2026-10-23: developer profile `vwb-Developer-535002863113`
  can list KMS keys and Secrets Manager entries in `us-east-1`. No secret values
  were read or created. App-role GetSecretValue/Decrypt and secret-write access
  are not verified. Recommended storage is Secrets Manager encrypted by KMS;
  no secret-store adapter or IAM change has been made. Bedrock/AgentCore access
  audit completed: developer and app roles are denied service listing; app-role
  simulation denies invocation. No paid calls or IAM changes were made. See
  [access evidence and enablement steps](AWS_AI_ACCESS.md).

- Join expiry recovery (2026-10-22): structured `DATASET_EXPIRED` response; browser reopens durable inputs and retries once, preserving tab configuration. Non-expiry errors do not retry; uploads require re-upload. API suite: 39 passed. Browser suite: 14 passed, including failure cleanup and repeated same-label results querying a new ID. Codex and OpenCode GLM max reviews passed after the repeated-result fix. Deployed and verified at `4226cb9`: SSM `1897f444-ec13-4a0d-a03b-ecec80c99a1e` reproduced a structured expired handle, reopened sources, and joined samples to OMOP person in Aurora with 5,000 rows, no truncation. Test-created handles were closed. Browser automation used local mocked API flows; live Aurora validation used the deployed HTTP API. The screenshot's `cost.cost_event_id = variants.variant_id` is not a valid relationship. Use person → samples (`person_id`) → genotypes (`sample_id`) → variants (`variant_id`). Correct full-source genetics joins succeeded in live Aurora (1,000,000 result rows; bounded preview). Earlier statement timeout was not reproduced and is not claimed fixed. The global eight-dataset cache can evict open tab handles; diagnostic opens may have contributed.

- Dev app verified healthy at `9c81943`; Vertex AI provider is present but project/location/model remain unset (no live inference). **Synthetic genetics demo COMPLETE:** Aurora `genetics_demo` has 5,000 linked samples, 200 annotated synthetic variants, and 1,000,000 genotypes. Live Dashboard API join to OMOP returned 5,000 rows using Aurora; planted pattern matched 500 persons/10,000 genotype rows. Table listing/open passed. Annotated CSVs and manifest uploaded to `nextflow_outputs/_studio_imports/genetics_demo/20261022/csv/`. Real database tests: 3 passed. See [demo guide](imports/GENETICS_DEMO.md). No OMOP source tables changed.

- Vertex AI provider implemented separately from Gemini API-key access. Uses server ADC and environment project/location, refreshes tokens per model call, and shares validation across filters and both assistants. Focused backend suite: 27 passed; no live Vertex inference or billing validation yet. User project/license clarification pending; do not claim free access.

- Schema browser/join UI fix (2026-10-22): normal Aurora listing now includes accessible non-system schemas with separate schema/table metadata. Opening, joins and saved-view reopen preserve schema; same-named tables remain distinct. Join editing hides the prior dataset toolbar/charts, and unrelated first columns are no longer default join keys. Production frontend build passed. Combined browser and real PostgreSQL API outcomes: **10 passed in 13.38s**. Live dev update verified at `5359072`: table API lists imported schema, and normal open of `cms_synpuf_100k.death` returns 4,466 rows with schema retained.

- **2026-10-22 CMS SynPUF import COMPLETE:** SSM `8c48e559-4d0f-4382-84b6-32577eebfc06` succeeded. Aurora `cohort-dash-db-20261005`, schema `cms_synpuf_100k`: 24 tables, 121,444,089 rows, 100,000 distinct people. Source/file/loaded counts and person references passed. Running Studio HTTP detection returned `cdm:true`; default cohort counts 90,085 persons with observation periods out of 100,000 total. CDM version correctly remains null. This supersedes all export/waiting/stopped/import-in-progress notes below. Do not rerun import. Clinical concept search, nontrivial cohorts, and multimodal joins still need live outcome validation.

- User screenshot (2026-10-21) shows the running UI at **103e7218d**, Aurora `cohort-dash-db-20261005` selected, and “No OMOP CDM found”. This supersedes the earlier stopped-app observation; it verifies the displayed version, not successful cohort queries.
- User clarified CMS SynPUF collection is the source and Aurora is the destination. Do not assume collection data is already in Aurora. Read-only workspace resource listing found the Aurora target but no resource named/described as CMS SynPUF. Files inside existing buckets have not been checked. Collection export/resource path is still required.
- Requested UI implemented: select an Aurora database in Explore, then choose OMOP cohorts in Explore mode. Removed the global OMOP tab and duplicate database selector. Editors keep separate session state for each visited Aurora resource. Production build passed. Codex found no confirmed blocker; OpenCode GLM max follow-up confirmed the navigation and test-selector fixes. Isolated suite: 152 passed plus one incorrect tab-title assertion; after correction, all 8 frontend browser tests passed in 11.38 s. The unrelated db.py edit was excluded. Review logs: `/tmp/cohort-omop-navigation-codex.txt`, `/tmp/cohort-omop-navigation-glm-final.jsonl`.

- `wb workspace describe` confirmed `bugbash-nextflowonaws`, UUID `5b932a68-43d4-432b-834c-9662e7dd0151`, server `dev-stable`, AWS environment `dev`.
- `wb app config list` confirmed **Cohort Studio** uses this repository, branch `cohort-dashboard`, and path `src/cohort-studio`.
- Latest `wb app list` check reported all dev Studio instances stopped, including **Cohort_Studio_EC2_MCP** at [dev app](https://workbench-dev.verily.com/app/a54c0049-6905-46c3-93ad-2fe2973cf9b9/). No browser session was available for runtime verification. These are observations, not permanent state.
- Previous published joins/cache release: **`3eca60141b525b05146c384e6b1c6a24eea62110`** on `origin/cohort-dashboard`. Publication does not verify that a dev app has fetched or run this SHA.
- Earlier OMOP release: **`c911229deb8dcac409880ba114bba7e36c2d0501`**. Its release snapshot with original db.py passed **294 tests in 27.90 s** before publication.
- Earlier cleanup release used the same in-app update path and passed **127 tests in 20.31 s** from an isolated snapshot. The unrelated local `db.py` override and `.cursor/settings.json` are excluded from those historical release snapshots.
- Deployment attempt: `wb app start --id=Cohort_Studio_EC2_MCP --workspace=bugbash-nextflowonaws` failed with `UnsupportedOperationException: Starting this type of app is not supported.` Start the AWS app through the Workbench UI. Its startup self-update should fetch the published branch; the in-app Update action is also available once running. Runtime SHA is **not verified**.
- Browser automation has no available browser in this session. `wb app update` only supports GCP in the installed CLI. The app's HTTP update endpoint is behind the Workbench browser proxy. No remote update was sent.
- The existing restart/update mechanism fetches the **pushed** branch. A local test pass does not update the dev instance.

## Join improvements (2026-10-21)

- Added full Aurora query scope for same-resource joins, explicit distinct entity counts, bounded durable join recipes, column settings, and a common join-key control.
- Live counts, filters, aggregates, numeric ranges, Compare and Derive cover the full source. Dataset chat remains loaded-row-only and is hidden on database-backed tabs.
- Database-backed **Export TSV** runs as a background Aurora cursor job. The UI shows row progress, supports cancellation, and links the file after completion. Limits: two workers, eight retained jobs, 2 GiB per job, 4 GiB total, one-hour finished-job TTL, 30-minute job runtime and five-minute SQL statement timeout. Files use temporary app-container disk.
- The older synchronous export, materialization and S3 workflow export still cap at 100,000 rows. No Aurora schema, Aurora resource or DuckDB service was added.
- Same-resource source recipes use validated Pydantic models and survive saved-view reloads. Derived recipes store a base and validated operation; client SQL is not accepted.
- Earlier join/cache snapshot passed **146 tests in 27.67 s**, excluding the unrelated local db.py override. The previous streaming release frontend build passed and `test_frontend_e2e.py` passed **7 tests**, including streaming export and live Compare/Derive. This is local evidence, not live Aurora or Workbench deployment verification.
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

- Streaming/full-source tools: isolated release snapshot passed **152 tests in 49.35 s**, no skips, with the unrelated db.py edit excluded. Final cleanup, polling and saved-settings fixes are included. Codex and OpenCode GLM max found no confirmed release blocker. See [review and limits](REVIEW_2026-10-21_STREAMING.md).

- Previous join/cache snapshot: **146 passed in 27.67 s**, no skips, from an isolated copy with the unrelated db.py edit excluded. Frontend production build passed. Codex CLI (`gpt-6-luna`) and OpenCode GLM max approved the reviewed scope. See [review evidence](REVIEW_2026-10-21_JOINS.md).
- Previous streaming UI scope: production build passed; all **7** tests in `app/tests/test_frontend_e2e.py` passed. Browser mocks do not verify live Aurora exports or a deployed Workbench app.

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

- Highest product priority: durable full-source OMOP cohort inputs for multimodal joins. Current cohort opens are capped frames without saved source recipes. Verify same-Aurora cohort-to-modality joins beyond the preview and save/reopen before calling this a reusable data cube. See AGENT_PLAN and architecture.md.

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
- 2026-10-21: Published joins/cache release `3eca60141b525b05146c384e6b1c6a24eea62110`. Follow-up release adds full-source Aurora Compare/Derive, durable derived source recipes, and bounded streaming TSV jobs; its isolated snapshot passed 152 tests and independent Codex/OpenCode GLM max review. Latest `wb app list` showed all dev instances stopped; no browser session or live datasource validation was available.

### Concurrent work detected

After the first full test run, `app/db.py` gained `STUDIO_LOCAL_AURORA` support from an
unknown concurrent editor. This was not part of the assigned agent changes.
It is preserved and excluded from this release. No dedicated local-mode test
was added by this session. A separate release snapshot uses the original db.py.
