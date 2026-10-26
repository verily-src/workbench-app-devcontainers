# Cohort Studio project state

Updated 2026-10-26. This is the shared project memory for Codex, Claude, Cursor, and OpenCode. Update this file after material changes. Record evidence, not assumptions.

## Latest local change

- Top alignment: Data sources header now shares the 46px navigation height/background/border; removed sidebar top offset. Build and two browser checks passed; screenshot inspected. Deployment pending.

- DEPLOYED ecec9861a2111f31e8118c9446e1e9eb64a2de54: sidebar Data sources heading and compact available count. Build and two browser checks passed; screenshot inspected. Update3144d1cb-e430-47e2-a79e-97f6fe6bd6f1; active SHA/health verified b88fdadc-e967-498a-ac11-d80d909f2573.

- **DEPLOYED 5b7bcb2c89f5e209a499b3cc99b93125282c49ed:** direct PubMed/bioRxiv adapters. Update SSM `46915992-8823-40a8-9f1a-18d62647c1c1`; SHA/health/frontend/backend activation verified `46ff060a-ef63-444d-8fd3-bee7548ce5de`. Live MCP HTTP calls from app container passed: PubMed asthma returned PMID26335832; bioRxiv cancer window2024-01-01→2024-01-02 returned DOI10.1101/2023.12.31.573735 with9records scanned/220window and truncated=true (SSM `2371124f-c867-4619-a06a-e5e7445ecfba`). Local combined83 tests plus1 actual MCP HTTP test passed. Live LLM-generated interpretation and user-key authenticated search not tested; tool calls used existing server settings without exposing key material. No workflow submitted.

- **Direct literature adapters validated locally (2026-10-26), deployment pending:** Studio Agent and local MCP expose PubMed and bioRxiv searches through fixed official APIs. Optional NCBI key saved in encrypted secret store with safe metadata and redacted validation errors; Settings distinguishes built-in literature from external MCP. Clickable HTTPS citations render without HTML. Combined adapter/settings/Agent/API/browser suite: 83 passed; frontend build passed and Settings screenshot inspected. Public API smoke returned one PubMed and one bioRxiv result. bioRxiv is a bounded metadata scan (up to three 30-record pages) with explicit coverage, not full-text search. No clinical claim or workflow execution.

- **DEPLOYED 2dee4343f609557170d7170f6a8f6ee4e1b1bf3f:** priorities 3–5 and 7 release. In-app update SSM `8a208f18-6086-433c-ad30-49aa0478ed4a`; active SHA, frontend/backend activation and healthy API verified by `815ee874-b999-4c9e-9366-87924f2c35ae`. Live Aurora API roundtrip passed: 200-row join → saved materialized view → reopen/query → refresh; physical snapshots hidden. All four temporary datasets and temporary view removed, no cleanup errors (SSM `f37631ab-6d11-413a-b319-f02950381807`). Final source-dialog browser test and build passed; progress/source-dialog screenshots inspected. No workflow submitted. Live model cancellation and Athena/Iceberg remain unverified; live browser acceptance pending.

- **Priorities 3–5 and 7 validated locally (2026-10-26), deployment pending:** Agent streams progress with owner-scoped cooperative Cancel and compact response guidance. Saved managed-Aurora joins use asynchronous materialized snapshots with refresh and dependency-aware cleanup. Safe primary-key paging and bounded disk materialization protect large-data operations. Add data source supports PostgreSQL/RDS, S3 and Athena/Glue/Iceberg; Athena results retain decimal precision and require an enforced scan budget. Combined real PostgreSQL/API/runtime suite: 138 passed. Browser/API regression group: 14 cases passed after updating the display-name assertion; connector rerun 3 passed. Independent static review GO; OpenCode quota blocked. Live Athena/Iceberg remains unverified: discovered primary workgroup has no enforced scan budget. Cancel waits for the active operation and does not stop submitted workflows. No workflow submitted.

- **DEPLOYED 90727f12b5282f21127f93bbb0f1ee265cc0bfec:** tutorial/source UI release. Update command `431537cd-9a57-4a77-bfc5-6b491625bda6`; active SHA, frontend/backend activation and healthy API verified by SSM `7569fc3d-b9c0-452d-8618-41024234c002`. Local tutorial browser checks: 2 passed; S3/SQL-copy regressions passed. Live browser acceptance remains pending; no workflow submitted.

- **Tutorial and source entry update, locally validated:** tutorial v3 uses current schema/file selection, OMOP summary, Agent sessions and workflow review. Optional steps can be skipped without running jobs. Empty-state Load data focuses the source picker; sidebar starts below navigation; source types have distinct symbols. Two tutorial browser checks passed after fixing skip-state transition and a test selector; S3 and SQL-copy browser regressions passed. Vite build passed; empty-state screenshot inspected. Deployment pending.

- **DEPLOYED 5ac65a5dc6fc3f86770ae87e332b90e8cc628055 (2026-10-26):** release update SSM `60524782-57b1-47d6-aced-b29ce1216e7c`; active SHA, backend/frontend activation and healthy API verified by SSM `73edec73-0131-4f88-b71c-c9a006aca9f7`. Includes all-tab Rename, bounded source-recipe recovery after backend restart, typed copyable SQL and S3 join picker. Local validation evidence follows. Live browser interaction was not tested. No new workflow submitted.

- **Join/recovery UI release validated locally (2026-10-26):** typed copyable PostgreSQL SQL works for nested OMOP→samples→genotypes→variants (5537characters/977tokens, existing limits unchanged);73 PostgreSQL/SQL/join-source checks passed. Source-recipe404 recovery and Rename on every tab:3browserchecks passed in each tree. S3 grouped picker/copySQL browser/API-DuckDB group:3passed in each tree; builds passed. Independent SQL static review GO. Live existing Aurora200variants + S3 1dictionary produced1DuckDBrow, untruncated (SSM5d95b9ac-085b-45ed-8b02-4e3481c4906f). UI deployment pending. Browser reload still requires reopening saved views; this recovery applies to current tabs with recipes after backend restart.

- **DEPLOYED e23695cfced07575db68f151e5b4d1f59475f0db:** SHA/health/restart verified SSM32485bcb-87da-4044-8f0f-35adea51ac1f. Specific plan113d6295 reconciled to verified FAILED run4ad21381 with full definitionUri length error (SSM8295b431-67ca-46f5-be39-6ce1d4ae4550). No new run submitted. New shortened-path run remains untested until explicit user Run workflow approval.

- **Workflow staging fix validated locally (2026-10-26):** plan113d6295-b670-4b56-bc4b-6b5f81d464b4 exported1475rows and Workbench created run4ad21381-b706-4f3a-925a-15b0d7a9fed4, then FAILED: generated definitionUri259characters exceeds HealthOmics256 limit (SSM a778638f-9ac6-44e5-ae6c-0b793de2b4fa). Short output paths/job names and pre-submit validation added; recovered failed plans retain service failure instead of stale uncertainty.61 PostgreSQL/API/workflow/result checks passed. No duplicate run submitted. Deployment pending.

- **DEPLOYED 5d07adb4230028ed311d645ce8808a7699ee24e9 (2026-10-26):** pushed to cohort-dashboard and applied via the in-app update endpoint (SSM `260c79bf-5889-41f4-86cb-87c9ad7e42ec`). Active SHA and successful backend/frontend activation verified by SSM `ec71ae57-1ef7-4134-951b-55c0d0b988d3`; its health check overlapped restart. Follow-up SSM `2611a46e-3eb2-4c35-a425-97f1b4cbd7b1` verified HTTP 200 for health, owner-scoped session listing and history with a fresh anonymous owner (empty results expected). Includes workflow approval stop, new/close/reopen chat workspace and setup-only integrations panel. No live model inference, workflow submission or live browser acceptance claimed. OpenCode retried after reported subscription activation but still returned free-usage-limit errors for GLM5.3-flash-free/max; no verdict.

- **OpenCode review retry 2026-10-26 blocked:** GLM `opencode/glm-5.3-flash-free` with `--variant max`, retried with `--pure`, returned “Free usage limit reached.” No review verdict or paid fallback. Implementation/test/deployment state is unchanged.

- **Local agent hardening and chat workspace validated, not deployed (2026-10-26):** ready workflow proposals stop the runtime before remaining batch tools or model calls and finish successfully at the turn limit. New chats have isolated server context. Agent has a left session list with owner-scoped Aurora titles, close/reopen without history deletion, stale-response guards, and responsive light/dark layout. Integration setup status includes PubMed/bioRxiv/arXiv and Settings navigation; external MCP tools are NOT callable by Studio Agent. Validation: combined PostgreSQL/API/runtime/provider/settings/browser run had 161 passed and one screenshot-test setup failure; after correcting that test and mobile sizing, focused fresh-build browser/API run passed all 4 checks. Root and candidate frontend builds passed; desktop/dark/mobile screenshots inspected. Independent static backend review GO. OpenCode GLM max stalled with zero output and was stopped; no verdict claimed. Paid provider inference and live deployment were not run. Existing Anthropic credit limitation remains unverified.

- **DEPLOYED 2d8e5e8f09c181ca486988efe3cad8c0f36a351e:** SHA and health verified (SSM `584ba3ae-1af5-4820-986b-7a8420dff591`). Deployed OMOP count/open both returned 200 and 29,553 people with database scope and retained demographic concept IDs; scoped turn limits and distinct-entity tool contract verified without model inference (SSM `91b6c290-c89d-49e5-baf2-04b9d1a99f68`). 112 combined local checks and browser checks passed. Candidate live join/preparation reached a ready 1,475-row plan; no workflow was submitted. Final narration with the new Studio 16-turn budget remains unverified because Anthropic rejected the retest for insufficient credits. Restore credits and repeat the agent evaluation; do not mark that last check complete.

- **Agent evaluation pre-release validation:** 112 combined PostgreSQL/API/runtime/provider checks and browser checks passed. GLM static runtime/filter reviews and independent final delta review returned GO. Live candidate verified 29,553 observed Female cohort members (birth years 1930–1950), 295,000 database-scope joined genotype rows and 1,475 rows for SYN_VAR_0021. Projection-guided preparation produced a ready plan with all six workflow columns and no errors (SSM `532126a0-d191-4858-8ce4-fe78c60e9935`), but the eight-turn chat ended at its limit after preparation. Studio Agent now has a validated 16-turn budget (generic chat stays eight), unchanged 600-second/64-call limits, and guidance to stop at the ready proposal. The final provider rerun was blocked before model execution by insufficient Anthropic credits (SSM `c735e789-e71e-480d-a627-ae8272c8f563`). No new workflow was approved or submitted; successful live final narration under the new budget is not claimed. Fixes also cover safe validation feedback, retry loops, truthful status, dated specs, exact identifier filters, raw demographic IDs, unique join projections and distinct-person query support.

- **DEPLOYED 9b91aa08286055c92af9d1410044db0f58d5a453:** SHA and healthy API verified (SSM `0aa6a525-88d9-4d11-9db2-a884750bbeb4`). Deployed condition_era API open passed in 4.70 s; all four charts and preview passed in 15.12 s with exact 9,643,957 totals (SSM `61fd0bb6-03a0-43ce-b332-f5d8b8030b0d`). Owner plan listing returned 200. 130 combined checks, new query-error and workflow-result browser tests passed; OpenCode recovery follow-up GO. Existing 1,475-person legacy workflow outputs verified, but no new checksum-producing cloud run or live browser clicks are claimed. Agent dashboards now support verified workflow result tools and durable plan recovery.

- **Validated follow-up candidate, not yet deployed:** 130 combined PostgreSQL/API checks plus browser tests passed. Real Aurora condition_era failure reproduced: 9,643,957 rows, ID histogram 504; native numeric OID path and duplicate-scan removal returned all four full-source charts and preview in 15.26 s (SSM `28a8beaf-a551-4f40-96a0-b84c315b4cef`). Query errors now stay beside the charts with retry. Real legacy workflow output verified: 1,475 people, six strata, 431 carriers/1,044 noncarriers, dictionary checksum and count/schema checks (SSM `4eb99d26-ea06-4cd3-9d8c-ea3814705b0c`). Workbench output UUID lookup now refreshes an unmapped cache entry strictly by UUID. OpenCode initial recovery blockers fixed; follow-up GO. Additive durable plan migration passed on existing Aurora with managed permissions unchanged (SSM `580d5f23-87f0-435a-b357-27179bc27d50`). Updated demo analysis uploaded to its existing nextflow_resources path; new checksum-producing cloud run not yet performed.

- **Workflow result follow-up candidate, not deployed:** durable owner-bound Aurora plans with atomic approval and no automatic retry of uncertain submissions; completed result verification and dashboard loading from checked bytes. Combined PostgreSQL/API regressions: 116 passed. Verifier/workflow manifest tests: 19 passed. Live legacy S3 check and external review running; UI validation in progress.

- **DEPLOYED e368c3ac63cf1bde3ed4803d046281fbcf2feff3:** SSM `53eb91c8-08a4-4a46-a035-f072d4a4fdc8` verified active SHA, healthy API and successful restart. Agent mode local suite: 97 passed; browser/build checks passed; OpenCode GLM max found no confirmed blockers. Live provider dashboard check passed (SSM `58aeb041-9212-458e-8290-c20d0002364d`): HTTP 200; agent inspected cms_synpuf_100k.person, built a database-scope 100,000-row gender dashboard (55,612 female / 44,388 male), grounded labels through concept search, and restored two conversation messages via history HTTP 200. No live browser clicks were performed. No workflow submission or output verification is claimed for this release.

- **Agent mode candidate, not deployed:** bounded Aurora/S3 discovery, Jev join evidence, OMOP/dashboard recipes and owner-scoped Aurora history. Explicit workflow approval validates joined-column mapping and prevents duplicate submission. Local combined PostgreSQL/API suite: 97 passed; Agent browser test and both builds passed. The older cohort-agent test now uses real session storage and configured provider fixtures, and passes. OpenCode GLM max static review: no confirmed blockers; noted in-process TTL/cap limits and ambiguous remote failures. It did not run tests independently. Live inference and output verification not claimed.

- **Final active release 4a147d99e62c4bd9c79e610fbc43a00260a9acd2:** SSM `322b0dbc-552a-400e-ba30-f36288233707` verified SHA, healthy API and successful restart. Includes default Jev model fallback; 51 isolated Jev/settings checks passed. Live OMOP reopen and Jev inference passed immediately before this follow-up on 790219ca1. Agent mode is a next-phase local backlog item, not implemented by this release.

- **LIVE checks passed on 790219ca1:** SSM `edd81d00-0721-4f9a-882c-39479c60a584` verified OMOP saved-source reopen at 29,553 people with matching first-page data and database scope. Jev token was readable but model blank; setting `jev-latest` resolved it. SSM `7603f89b-2648-4d8e-a1a2-a4653cf9ceb6` returned `used/configured:true`, valid sample_id recommendation and no Jev warnings. A follow-up code default uses `jev-latest` when no model is saved; explicit environment/saved models remain honored. Model reference: https://docs.typesafe.ai/models.

- **DEPLOYED 790219ca12bd22b612e899b4c5b617445fb67cb9:** SSM `70a661a3-3b5c-436e-b29b-e0747ca02bfd` verified the active SHA, healthy API and successful staging/restart. Includes live OMOP source recipes, workflow lineage, saved Jev token resolution, collapsible saved filter history and Light/Dark/System appearance. Live OMOP/Jev checks running; no live UI clicks or new workflow run are claimed yet.

- **Release candidate validated (2026-10-25), not yet deployed:** live OMOP recipes reopen and join in Aurora; derived queries retain compiler validation. `EXISTS` works for same-database semi joins while unsafe nested functions remain rejected. Workflow lineage links exact dataset/cohort, export, parameters and run events. Jev recommendations use encrypted Settings credentials with environment overrides. Aurora filter questions have collapsible history (last 25), retained in saved views. Settings adds Light/Dark/System appearance with persistent browser preference and chart contrast. Validation: combined PostgreSQL/API suite 106 passed; separate focused derive/SQL suite 81 passed; browser regression run 12 passed and one test-selector failure, corrected history browser/API rerun 2 passed in both trees; theme screenshot inspected. OpenCode GLM max static review found no confirmed blockers; it did not independently run the suite. Live Jev inference, new live OMOP reopen and deployment verification remain pending.

- **DEPLOYED assistant/settings hotfix 75f3a12e88d8d895b12485225dcb56bc62aa264e:** SSM `59334b4d-a590-4da1-aade-325b249df2a3` verified APP_SHA, healthy API, staged imports and successful restart. Local validation: five settings browser/API checks, three chat browser checks, 12 agent/runtime checks. Inline questions open the same dataset chat for loaded/disk-backed sources. Provider credit-dependent inference and live browser clicks remain unverified. OMOP recipe and workflow lineage improvements remain separate uncommitted changes.

- **Local fixes, not deployed (2026-10-25):** provider Save now sends only provider fields; MCP saves omit read-only `token_set`. Real Chromium/API checks: 5 passed. Disk-backed assistant tools use DuckDB with current filters and bounded previews; agent/runtime checks: 12 passed in each tree. Live user request reached Anthropic but failed for insufficient credits; user is adding credit. This supersedes the earlier no-key observation. Inline filter Ask now opens the same dataset Chat for loaded/disk-backed datasets (three Chromium checks passed); database-backed filter-only support remains separate until live-source chat is supported. Existing live instance has no browser sidecar; isolation enforcement is unverified.

- **Final patch DEPLOYED, 2026-10-25:** `29df2b9095d0d3dfbb36591ebb20e03c17203dc0`
  is active and healthy. SSM `c83661f2-4866-4c38-91df-616a37402c83` verified
  APP_SHA, health, staged imports and successful activation/restart. This adds
  managed S3 folder defaults and records the verified HealthOmics artifact paths.
  Final live evidence: 29,553-person OMOP cohort → 1,475 matched genotypes →
  completed Nextflow run → six aggregate strata reopened through dashboard API.
  Chat interpretation still needs a saved provider key. Browser-side live clicks
  and Jev API connectivity were not verified. Indexed backlog remains local-only.

- **LIVE demo verified, 2026-10-25:** release `31515dc27fa0435f866083425c74566b38cc9d9f`
  is active and healthy (SSM `a60624b4-bf0d-4222-b7ef-48767b35a67a`). Settings
  now exposes encrypted Jev key save/remove, provider Save/Test feedback,
  interactive tutorial, and separate built-in guidance/document enrichment.
  The real OMOP cohort count/open matched at **29,553 people** (gender 8532,
  birth years 1930–1950, required observation). Joining those exact member IDs
  with Aurora synthetic genotypes and the S3 dictionary produced **1,475 people**.
  The live app exported and submitted all rows (SSM
  `5671fc01-f920-46cb-b829-6bddb6f9c9fa`). Workbench run
  `ceea2bdc-50fa-4922-a1a3-53e2a3e2b3fe`, HealthOmics **4806228**, completed.
  Final manifest includes engine ID and `/pubdir` paths. Live output/API check
  `6b5461e5-fcfc-4894-9569-9587a88ab95d` verified six summary strata,
  **431 synthetic carriers + 1,044 noncarriers = 1,475**, exact manifest URIs,
  and successful dashboard open/query. A separate 10-row Aurora/S3 join passed
  (`dd3fd7b2-bb51-48b9-91c4-9a506ea035e2`). Provider configuration reports
  Anthropic / claude-opus-5 with no saved key; live interpretation is unverified.
  Jev connectivity remains unverified. No IAM changes were made.
  Validation: 67 combined candidate checks, focused real-helper regression,
  10 workflow analysis checks including engine-path CLI coverage, and three
  workflow browser checks including managed-folder defaults. OpenCode GLM max
  found no confirmed code blocker; its requested live workflow check is now done.
  Follow-up source patch includes corrected manifest paths and managed S3 defaults.

- **DEMO registered, 2026-10-25:** Workbench workflow `cohort-genetics-demo`
  (UUID `dc95c029-5a41-42f7-81bc-49e2e7a69173`) points to
  `nextflow_resources/cohort-studio/demo-v1/main.nf`. Synthetic input and variant
  dictionary are uploaded beside the definition. Real local Nextflow execution
  and the pinned Linux runtime both produced summary, dictionary and manifest.
  Combined candidate API/browser suite passed 67 checks; a later regular-workflow
  regression test uses the actual CLI helper. Cloud smoke run
  `6901dae0-3e34-47c3-b490-8a6e15ab4c6c` failed before execution because a future
  output URI was treated as an S3 input. Corrected cloud params use plain output
  bucket/key; retry pending. No successful cloud output is claimed yet.
  Jev key Settings save/remove is locally validated through the encrypted store;
  Jev API connectivity is not verified. App changes are not deployed yet.

- **LOCAL validated, 2026-10-25:** Knowledge Base now separates built-in
  assistant guidance from attached project documents. Attachments enrich context
  and do not replace trusted instructions. Shared-corpus/provider disclosure is
  retained. Root and candidate frontend builds passed; document upload, search,
  reload and removal browser test passed in both trees (one each). Not deployed.
  AI Settings Save/Test feedback also passed three mocked browser tests; live
  provider inference remains unverified.

- **DEPLOYED, 2026-10-25:** `1a220565ba8961ee8bc8bed37084c60519fa2f5c`
  is active on the existing dev app. After SSO refresh, SSM
  `eb3ed61f-416c-420b-bc4e-09187ed5d262` verified APP_SHA, health OK,
  staged imports, frontend/backend activation and restart. This supersedes
  the earlier activation-pending status.

- **UI PATCH validated, 2026-10-25:** contained wide SQL editors/results within
  the main pane; SQL result tabs now support inline naming with saved-view
  persistence. Sidebar selection is source type → datasource → schema → table;
  S3 offers folder/file filtering. Workflow selection is first, separate from
  input/output S3 folders; unavailable registry is reported. Candidate build
  and root TypeScript check passed. Nine targeted checks passed across runs,
  including real PostgreSQL-backed OMOP browser/MCP/cohort-assistant flows
  (provider stub, real tools/storage). Wide SQL layout was inspected at 900px
  and 1440px. Live registry check found 18 registered workflows, but no demo
  analysis input/output contract has been verified. No workflow was submitted.

- **DEPLOYED, 2026-10-25:** `2f623574a28a3fc6bc1b6b379300bb1539f03f04`
  published from the isolated worktree and activated through `/api/admin/update`
  on the existing dev app. SSM `9f756f1d-9f7a-4e53-ae33-71139c581c81` verified
  running SHA, health 200 and successful staged activation/restart. Candidate
  backend/browser suite passed **148 checks in 39.49s**, plus a focused browser
  recheck for cross-source scan consent. PyArrow is an explicit dependency.
  Release keeps synchronous saved-view recipes; materialized-view jobs, new
  datasource registration and Veibot drafts remain excluded. Root worktree and
  `app/db.py` were preserved. Live smoke
  `1c0c4b26-3626-4223-bd8e-a28162c11a06` passed: JSONB metadata table opens
  (1 row, 7 columns); generated Aurora SQL validates; the real join returns
  10 expected rows with a durable source recipe; unified saved views returns
  1 view and no unavailable stores. Temporary datasets were closed. Live model
  inference and streamed-browser interaction were not tested in this release.

Local-only indexed work queue: `docs/LOCAL_BACKLOG.md` (do not commit or publish).

- **LOCAL ONLY, 2026-10-25:** fixed JSONB table profiling (`unhashable dict`),
  SQL CAST validation inside JOIN predicates, SQL source page ordering, and
  streamed database cursor initialization. BigQuery retains its sampled loader.
  Disk-backed S3/catalog and cross-source joins retain full staged data; each
  DuckDB connection has a 2 GB memory limit and a 1 TB spill limit, with a 10 GB
  warning and a 1 TB data budget. Current-batch bytes are checked before insertion;
  registration failures remove owned files. No change to native Aurora S3 access.
  Saved Views now aggregate permitted stores without a datasource picker. SQL
  mode hides visual join controls. Edit join restores durable input recipes and
  creates a revised result tab without replacing the original. Visual preview
  exposes compiler SQL and bound parameters separately. Knowledge storage is
  separated into `knowledge_store.py`; its UI now has grouped, responsive fields.
  Local PostgreSQL checks: API + SQL source **63 passed**, join source + live
  derive/compare **13 passed**, disk data **5 passed**. Newly built browser/API
  checks for knowledge, saved views, edit join and SQL mode **8 passed**; frontend
  build passed (existing bundle-size warning). Codex Luna follow-up found no
  confirmed blocker in disk budgeting/cleanup, knowledge service or SQL generation.
  OpenCode GLM max found a UI/API contract mismatch: SQL was read from preview
  instead of validation. Fixed the binding; the corrected built-browser check
  passed and now verifies SQL before Preview, clearing on invalid key selection,
  and restoration after selecting a valid key. Preview deliberately has no SQL
  field. This additional check supersedes the earlier mock-based SQL-display claim.
  OpenCode's narrow recheck confirmed the blocker is resolved. Its broader review
  confirmed SQL-mode separation, original-result retention and temporary-input
  cleanup; it noted duplicate DuckDB SQL builders as maintenance debt.
  These changes are not published or deployed; live remains `194f397b5`.
  Demo scope: [OMOP + genetics round trip](DEMO_OMOP_GENETICS.md). No notebook or
  workflow job was run as part of that scope.

- **S3 incident verified, 2026-10-25:** `bench9232_ho_data` has the correct bucket
  and empty prefix, and the Workbench resource profile resolves to the expected
  external-access role. AWS explicitly denies ListBucket because no VPC endpoint
  policy permits it. Internal `bench9232_ho_data_internal` lists 28 files. Evidence:
  SSM `7dcbb268-843f-42b0-a981-32d6a806a7bd`. Profile regeneration did not resolve
  the external denial. No IAM, endpoint policy, or alternate access route was
  changed. The deployed memory release did not change the S3 listing implementation.

- **DEPLOYED and storage-verified, 2026-10-25:** `194f397b5cd706b76a2b5fdcc9a8614bb302daa5`
  is published on `cohort-dashboard` and running in the existing dev app via
  `/api/admin/update`. Health passed; update log verified staged imports,
  backend/frontend activation, and restart. Candidate release: 70 backend +
  4 Chromium checks, plus 6 managed-migration checks. Live Aurora conversation
  round-trip/owner isolation passed. History HTTP endpoint returned 200.
  Key migration found zero legacy keys; active Anthropic provider has no key,
  so live model inference remains unverified until a provider is configured.
  Synthetic-key verification `43ac38e7-099d-4d60-af46-056bde749b14` passed AES-GCM
  persistence, mode-0600 files, read after a fresh process, and cleanup. No user
  key was displayed or added. Same database `_studio_agent` uses unchanged
  managed permissions (not private). Refresh the app to test; Tutorial is in
  the header and provider setup is in Settings.
  Release commits were made in detached `/private/tmp/cohort-memory-publish`;
  root worktree/index were preserved and local root branch remains at old HEAD.
  Do not blindly stage the root tree: it still contains paused/unreleased work.

- **Live storage verified, 2026-10-25:** resumed the existing dev app. Managed
  migration `a1d3d00c-b2d0-42dc-bad3-9eb80f02a626` created all five `_studio_agent`
  tables and saved `/app/agent_store_config.json` for `cohort-dash-db-20261005`.
  Verification `c7bacae3-66b3-4eee-953a-899e2a2f71c0` passed a real Aurora
  conversation write/read and cross-owner rejection; synthetic records were
  removed. Existing database permissions were unchanged. Isolated release commit
  `367249557d6112fe60f78e972140431b04c283a1` is prepared; publication and app
  activation are tracked separately below when verified.

- **2026-10-25:** approved managed-access migration is implemented and tested
  locally, but its live attempt could not start (SSM InvalidInstanceId). Follow-up
  EC2/SSM checks failed because AWS SSO expired. Refresh SSO and confirm the app
  instance is running before retrying. No successful live migration, release
  publication, key migration, or app update has occurred.

- **Storage decision superseding the private-schema blocker, 2026-10-24:**
  user explicitly accepts non-private agent storage in the existing Aurora
  database under the `_studio_agent` prefix. Migration now supports explicit
  `--managed-access`, which leaves all Workbench-managed permissions unchanged.
  Default migration still requests private permissions. Prefix/UI exclusions
  are not database privacy; database readers may read conversation data.
  API keys remain in encrypted storage, not these tables. Six local checks
  passed, including managed migration and persisted conversation round-trip.

- **Isolated release verification, 2026-10-24:** candidate backend suite passed
  70 checks; production frontend build passed. Candidate Chromium checks first
  caught a missing tab-identity fix during selective assembly. After restoring
  dataset-ID updates and keying ChatWidget by dataset ID, all four browser
  checks passed in 8.83s (history restoration, late replies, knowledge UI,
  tutorial). The stale API-key hint UI/type mismatch was also removed.
  Candidate still awaits approved Aurora private-schema provisioning; do not
  tell the user to update or claim live key migration has occurred.

- **Integrated local validation, 2026-10-24:** 81 checks passed in 12.12s
  covering real PostgreSQL memory storage and sessions, provider adapters,
  encrypted local keys/recovery, admin configuration, knowledge retrieval,
  and Chromium chat/tutorial flows. Disposable database was removed afterward.
  Tutorial supports five steps, keyboard close/focus return, and saved progress.
  Shared typed admin configuration is the first structural refactor; broad
  routing/module changes remain separate. This run validates the working tree;
  the isolated release candidate has its own validation gate.

- **Live release blocker, 2026-10-24:** AWS SSO is restored; the app instance
  `i-0e9d71494595f205c` is healthy on `ad62261767`. The datasource resolver
  needs `cohort-dash-db-20261005`, not the resource UUID. Migration command
  `9115528e-59b9-4b25-8794-34f0e9bbc6f3` failed because Workbench's database
  policy prohibits the app role from running GRANT/REVOKE. The transaction
  rolled back; memory configuration was not written. Do not remove permission
  controls to bypass this rule. Administrator-provisioned private storage or
  an approved dedicated Aurora resource is required before enabling memory.
  The isolated release candidate is `/private/tmp/cohort-memory-release`;
  nothing has been published or deployed. Tutorial browser flow and build
  passed locally; encrypted local-key checks passed (40, one socket test
  excluded pending integrated run). OpenCode read the memory files but did not
  return a verdict before it was stopped; review remains incomplete.

- **Release preparation, 2026-10-24:** all 70 local memory checks passed in
  9.65s using PostgreSQL and Chromium. AWS SSO expired and refresh failed;
  live Aurora setup and release verification remain blocked pending login.
  User authorized encrypted local key storage when KMS is unavailable; this
  fallback is being implemented and is not yet verified. Prepare a separate
  memory release snapshot to exclude paused join changes. After validation,
  refactor incrementally for clear module boundaries and typed interfaces,
  preserving user behavior; do not combine an untested broad rewrite with release.

- **Hosting decision, 2026-10-24:** one application container hosts Studio and
  LangGraph; inference uses general provider APIs and available models. No Qwen
  download or GPU provisioning. Bedrock/AgentCore hosting is deferred until
  access is available and verified. Existing browser isolation is unchanged.

- **Memory-only verification, 2026-10-24:** the final integrated run passed 69
  checks and found one real PostgreSQL long-reply storage failure. Fixed the
  message column from varchar(24000) to text, retaining application validation;
  all 14 affected store/session/OMOP checks then passed in 1.78s. Chromium
  verified history restoration and that a late reply cannot update another tab.
  The production frontend build passed. Tests used a temporary database in the
  existing local PostgreSQL container and removed it afterward, avoiding the
  host initdb shared-memory limit. No live Aurora migration or deployment ran.
- Conversation history now resumes the latest owned session when no session ID
  is supplied. Failed/expired turns retain a generic failure message. Browser
  requests no longer send conversation contents as authoritative history.
  Independent review found the tab-index race, now fixed with dataset-ID updates;
  its OMOP resource-race report was not confirmed because Editors are keyed by
  resource ID. OpenCode GLM max produced no output in two attempts and was
  stopped; no successful OpenCode verdict is claimed.

- **2026-10-24, in progress / not deployed:** dataset and OMOP chat now use
  LangGraph with bounded, validated tools and provider adapters. Aurora
  `_studio_agent` stores versioned prompts, sessions, messages and step telemetry.
  Conversations are retained; the cleanup command expires telemetry after 30 days.
  Browser-owner cookies bind sessions; histories restore through owner-scoped APIs.
  Internal schemas and legacy agent telemetry tables are excluded from public
  table/SQL sources; the user-facing agent-turn feed is disabled. Requires explicit
  STUDIO_AGENT_RESOURCE_ID and the migration script before live chat can run.
  Integrated local checks before sidecar cancellation: **60 passed in 9.97s**, including real PostgreSQL
  history/ownership tests, Chromium chat restore,
  and fake OpenAI-compatible openweight endpoint. Frontend build passed.
- **Latest scope:** keep the monorepo and existing container layout. LangGraph
  runs inside the Studio backend with API inference. The experimental agent
  sidecar/gateway files, broker and temporary containers were removed at the
  user's request. Self-hosted Qwen/GPU work is deferred; no weights downloaded
  or GPU resource created. Focus now is durable agent memory.
- Large-join/disk-backed exploration edits are paused and remain uncommitted
  draft work, not a verified release. Their last expanded test found a
  count-by-group iterator bug, now fixed but not reverified after local PostgreSQL
  hit the OS shared-memory limit. Do not ship these as part of a memory-only
  update without separate validation.

- **2026-10-24, local only:** Aurora table opens now keep a database-backed
  source recipe. The frame in memory remains a 100,000-row preview; dashboard
  counts, filters, charts, and row pages use the full Aurora query. Live-backed
  datasets and derived columns no longer report the preview as a sampled
  dashboard. Cross-resource joins still require consent and use loaded rows.
  Targeted local validation passed: **40 tests** in `test_live_derive.py` and
  `test_api.py`, including a real PostgreSQL fixture with 100,005 joined rows
  and a query matching a row beyond the preview. S3, BigQuery, Athena, and
  catalog-source full-source paging are not covered by this change. No deploy.

- **2026-10-24, local only:** the OpenAI-compatible `openweight` provider can
  use an administrator-configured endpoint and model. The Qwen/Qwen3.8-27B
  profile documents the official vLLM parser flags, non-thinking mode,
  bounded context, and an estimated memory budget. Config wiring test passed;
  fake endpoint/settings tests passed earlier. No model weights were
  downloaded and no model service or GPU instance was created. AWS account
  capacity, quota, placement, and pricing remain unchecked.

## Active project

- **2026-10-24, local only:** initial knowledge base uses SQLite FTS5 keyword
  search, without embeddings. Settings supports text paste and UTF-8 TXT/MD/CSV/TSV
  upload, search, and deletion. Dataset, OMOP, and join assistants receive up to
  four matching passages with source citations and untrusted-content instructions;
  MCP exposes read-only `search_knowledge_base`. Seven API/agent checks passed;
  frontend production build passed. Real Chromium → local HTTP flow passed
  upload, reload, cited search, and removal (1 passed in 10.07s). No live deployment or provider inference verified.
  Storage is app-instance shared, capped at 100 documents / 200,000 characters
  per document. Set STUDIO_KNOWLEDGE_PATH on persistent storage for durability
  across container replacement. S3 ingestion and embeddings remain deferred.

- **In progress, 2026-10-23 (not deployed):** PostgreSQL/RDS, registered S3
  Parquet, Athena/Glue Iceberg reads, Add data source, explicit loaded-row
  cross-source joins, saved materialized snapshots and refresh jobs, a durable
  Count by group workflow, Veibot join proposals, Jev Settings, MCP connection
  tests, and Secrets Manager/KMS key storage. Full integrated validation and
  final review are still running; do not treat this working tree as released.
- Local evidence so far: PostgreSQL connector discovery/OMOP/join/reopen/read-only
  checks passed against the running local PostgreSQL container. Workflow save,
  cache-clear, reopen and query passed against disposable PostgreSQL. Browser
  tests for connectors, snapshot job UI and Count by group passed before later
  Add source/Veibot/Settings additions; those additions need the final suite.
- OpenCode GLM max reviewed this update and identified Glue GetTables page size
  and Athena final-page deadline handling; both are fixed with boundary tests.
  Codex Luna findings about common column settings and explicit MV projections
  were checked against the code and not confirmed. Follow-up review is pending.
- **Live checks:** SSM `69a0433d-9a4b-4415-bd04-301bd05b0dc6` confirmed all three
  MCP entries (Workbench, bioRxiv, PubMed) have empty URLs and are disabled.
  SSM `27cc0c31-127a-4193-a004-18d15b6f04e2` confirmed the current app lists one
  Aurora database and nine S3 folders. No live MCP handshake is possible until
  an endpoint is configured.
- **IAM constraint:** live IAM simulation for `v0SaasDevAppInstance` returned
  implicitDeny for Secrets Manager GetSecretValue/CreateSecret/PutSecretValue
  and KMS Encrypt/Decrypt. No role policy was changed, and no user key was
  migrated or stored in AWS. New key writes fail closed when secure storage is
  unavailable; existing legacy keys remain readable until explicit migration.
- Knowledge-base integration is **scoped only** in
  [KNOWLEDGE_BASE_SCOPE.md](KNOWLEDGE_BASE_SCOPE.md): registered sources,
  versioned ingestion, candidate local EmbeddingGemma 2 embeddings, Aurora
  pgvector pending extension/grant checks, and actual MCP tool discovery.
  No embedding model, vector index, or knowledge ingestion job is installed.

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
