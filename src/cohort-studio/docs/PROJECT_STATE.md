# Cohort Studio project state

Updated 2026-10-20. This is the shared project memory for Codex, Claude, Cursor, and OpenCode. Update this file after material changes. Record evidence, not assumptions.

## Active project

- Active app: `src/cohort-studio/` (React/TypeScript/Vite/ECharts + FastAPI).
- Branch: `cohort-dashboard`; base commit at start of this work: `5fc68f9`.
- The Panel app under `src/cohort-dashboard/` is superseded.
- Use `uv` where available and Pydantic for API boundaries. Shared engine validation also applies to MCP and agent calls.
- See [README](../README.md), [root agent rules](../../../AGENTS.md), and [agent architecture and next steps](AGENT_PLAN.md).

## Verified delivery state

- `wb workspace describe` confirmed `bugbash-nextflowonaws`, UUID `5b932a68-43d4-432b-834c-9662e7dd0151`, server `dev-stable`, AWS environment `dev`.
- `wb app config list` confirmed **Cohort Studio** uses this repository, branch `cohort-dashboard`, and path `src/cohort-studio`.
- Latest `wb app list` reported **Cohort_Studio_EC2_MCP** stopped at [dev app](https://workbench-dev.verily.com/app/a54c0049-6905-46c3-93ad-2fe2973cf9b9/). The Oct 7 and Oct 20 Studio instances were also stopped. These are observations, not permanent state.
- User requested deployment to the known dev app. Release preparation targets `cohort-dashboard`; remote head before publication was `5fc68f9`. Runtime deployment is not yet verified. The unrelated local `db.py` override and `.cursor/settings.json` are excluded from the release.
- Browser automation has no available browser in this session. `wb app update` only supports GCP in the installed CLI. The app's HTTP update endpoint is behind the Workbench browser proxy. No remote update was sent.
- The existing restart/update mechanism fetches the **pushed** branch. A local test pass does not update the dev instance.

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

1. Preserve the concurrent db.py local-mode edit and Cursor settings outside the release. GLM follow-up fixes and final local checks are complete.
2. Publish the tested branch for `Cohort_Studio_EC2_MCP`, start/update the app, then verify `/api/version`, frontend, and real resource operations from inside the workspace.
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

### Concurrent work detected

After the first full test run, `app/db.py` gained `STUDIO_LOCAL_AURORA` support from an
unknown concurrent editor. This was not part of the assigned agent changes.
It is preserved and excluded from this release. No dedicated local-mode test
was added by this session. A separate release snapshot uses the original db.py.
