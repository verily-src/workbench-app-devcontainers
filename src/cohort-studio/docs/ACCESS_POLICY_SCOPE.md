# Cohort Studio: feasibility of Snowflake-style data access policies

Read-only study, 2026-11-04. Paths relative to `src/cohort-studio/`.

## (a) Identity and trust model today

- **No end-user identity reaches the app.** `agent_sessions.owner()` (`app/agent_sessions.py:30-36`) hashes a random `studio_chat_owner` cookie minted per browser; middleware (`:39-51`) only preserves it. No route reads an identity header or JWT (`grep` of `request.headers`/`x-forwarded`/`jwt`/`oidc` over `app/` finds nothing). "Owner" means "same browser profile" (architecture.md:661-663; PROJECT_STATE.md:130 "cookie-scoped fairness is not tenant authentication").
- **The only human identity known is the VM's `wb` login.** `views._actor()` (`app/views.py:39-51`) and `lineage._actor()` (`app/lineage.py:58-70`) stamp `wb auth status` email on saved views/lineage regardless of HTTP caller.
- **Data credentials are the app owner's.** `db.resolve_connection_string` (`app/db.py:43-74`) always requests `WRITE_READ` (CLI default is `READ_ONLY`); one cached connection string and one `_rw` engine per resource serve every query path (`app/db.py:303-326`). The password is a 15-minute RDS IAM token minted from the VM's Workbench credentials (verified with `wb resource resolve` on `omop-data-source`; DB users `omop_data_source_aws_byoa_testing_rw`/`_ro`). S3 uses per-resource AWS profiles (`app/db.py:125-142`, `app/duck.py:54`).
- **Platform scoping (verified read-only):** `wb app describe` returns `ownerEmail` and the proxy URL; `wb app` has no share subcommand; Workbench docs: "You cannot access the apps of other users in a shared workspace, regardless of your level of access to the workspace." Unauthenticated `curl` of the proxy URL returns the Workbench frontend HTML shell (cache-tag `workbench-frontend-root-config`), not the app's JSON. Sources: https://support.workbench.verily.com/docs/guides/workspaces/access_control_and_sharing/ and https://support.workbench.verily.com/docs/guides/research_data/aws/query_aurora/ (the latter: `WRITE_READ` "requires writer role or higher", so workspace role to `_rw`/`_ro` is the platform's only person-level data boundary today, and the app bypasses it by always requesting `WRITE_READ`). The Aurora resource is `SHARED_ACCESS`; `wb resource create aurora-database --access PRIVATE_ACCESS` exists and `describe` exposes `privateUserName/privateUserRole`.
- **Conclusion:** each Studio instance is single-tenant for its app owner. An app-enforced policy can constrain the AI agent, MCP callers, saved-view/lineage sharing and accidental export; it cannot constrain the owner, who controls the container, `self_update.sh`, the `wb` session and the RW token. Policies that must bind *people* have to live in the platform/database layer.
- **Unverified:** whether the proxy forwards any identity header to the container; whether workspace Readers can launch the app config.

Also: datasets are not owner-scoped (`app/main.py:1078-1089`); cache keys carry no policy (`app/query_cache.py:96-101`); the managed role rejects `GRANT/REVOKE` (architecture.md:669, PROJECT_STATE.md:394-402); materialization writes as `_rw` (`app/materialized_sources.py:52`).

## (b) Options

### 1. Database-enforced (roles, column privileges, views, RLS)

How: masked `security_invoker` views, `CREATE POLICY` on base tables, `SET ROLE`/`SET LOCAL app.user` at connection checkout.

Blockers: no per-user principal exists; Workbench provisions exactly two DB users per resource and rejects `GRANT/REVOKE`, so the app cannot create per-user roles or column grants. `CREATE ROLE`, `CREATE POLICY`, `ENABLE/FORCE ROW LEVEL SECURITY`, `ALTER DEFAULT PRIVILEGES` are **unverified** (DB is VPC-only; laptop cannot connect). Even if RLS can be enabled, the `_rw` table owner bypasses it unless `FORCE` is set, and can disable it.

Protects: nothing beyond today's RW/RO split without platform changes. With per-group DB roles minted by Workbench it becomes the strongest layer, covering exports, joins, agent, MCP, user SQL and `psql` from other apps.

Effort: S in-app (use `_ro` for reads, pass a session GUC); L overall as a platform feature. Phases: (1) app reads via `_ro`; (2) platform: group roles + grant-capable admin; (3) RLS keyed on `current_user`/GUC.

### 2. App-enforced policy layer

How: a declarative policy per resource (YAML; OPA/Cedar is overkill with one principal) with table allowlist, hidden columns, masking expressions, mandatory row predicates. Enforce by sqlglot AST rewrite (already a dependency) replacing each `exp.Table` with `(SELECT <allowed/masked cols> FROM t WHERE <predicate>)`. Projection-only hiding is insufficient for user SQL: `WHERE`/`GROUP BY`/`EXISTS` can infer hidden values.

Hook sites: `sql_source.normalize` table walk (`app/sql_source.py:87-98`; `internal_data.require_public_source` is the existing table-grant precedent); `live_query._execute_query` (`app/live_query.py:453-454`); `export_jobs._run` (`:328`); `joins._table_ref`/`aurora_sql` (`app/joins.py:360-392`); `disk_data._validated_live_sql` (`:428-443`, DuckDB staging); `live_compare`, `live_derive`, `group_summary`; `omop.py` hand-built cohort SQL (`:274-842`); `queries.list_tables` and `column_settings` (metadata); `materialized_sources`; `catalog.py` custom DuckDB SQL (audit A2); MCP `open_dataset`/`inspect_table`/`query_dataset` (`app/mcp_server.py:69-148`); Studio Agent tools (`app/studio_agent.py:29`). Cache keys need a policy digest; saved views, lineage and agent artifacts store SQL and must be re-validated on open; staged DuckDB files and exports predating a policy change need invalidation.

Protects: agent/MCP/prompt-injection access to sensitive columns, accidental export, leakage into shared saved views. Does not protect against the app owner or anything else reading Aurora directly.

Bypass risks: any missed site (23 files emit SQL); rewrite bugs; owner-editable policy file; separate logic needed for DuckDB/S3 and BigQuery; metadata routes.

Effort: M for Aurora-only column hide/mask; L for rows plus DuckDB/BQ, caches, persistence, agent/MCP. Phases: (1) policy model + shared rewrite in `sql_source`/`live_query`; (2) exports, joins, staging, compare/derive, OMOP; (3) metadata, caches, saved artifacts, DuckDB/BQ.

### 3. Platform-level separation

How: one resource (or workspace/data collection) per audience: de-identified schema or materialized copy in its own Aurora resource, membership via Workbench groups, data collections for publication. `PRIVATE_ACCESS` Aurora and group policies exist in CLI/docs (Aurora semantics unverified; whether data collections can include AWS Aurora is unverified).

Protects people: Workbench ABAC and IAM tokens gate who can resolve the resource at all, for every client. Weakness: coarse grain; copies drift without a refresh job; masking fixed at copy time; a user with both resources can link them.

Effort: S in-app (discovery already per-workspace), M operationally (reuse `materialized_sources`/`omop_load` to write a de-identified schema into a separate resource). Phases: define view set; materialize; share via group.

### 4. Hybrid

Option 3 as the people-facing boundary now; a narrow option-2 layer as defence in depth for agent/MCP/export paths; option 1 pursued with the platform team as the long-term enforcement point.

## (c) Recommended path and first milestone

Milestone 1 (S/M, app-only):
1. Resolve a second engine per resource with `--access-mode READ_ONLY` and route every read path through it (`sql_source`, `live_query`, `export_jobs`, `joins`, `disk_data`, `omop`, `live_compare/derive`, `group_summary`, MCP); keep `_rw` for `materialized_sources`, `_studio_agent`, `_studio_views`. These paths already declare `READ ONLY` transactions, so this is low-risk if test (0) passes.
2. Add a named static policy (`policies/omop-deid.yaml`: table allowlist, `hide: [person.person_source_value]`, `mask: {person.birth_datetime: date_trunc('year', ...)}`) and `policy.rewrite(expression)` replacing each `exp.Table` with a policy subquery; call it from `sql_source.normalize` and the `live_source["sql"]` builders.
3. Add the policy digest to `query_cache.make_key` and `_BaseCache._key`; invalidate on change.

Tests: (0) `_ro` can SELECT every table `_rw` created (loaded OMOP schema, `_studio_views`); if not, milestone 1 is blocked pending platform default-privilege support, since `GRANT` is rejected; (i) SQL source selecting or filtering on `person_source_value` is rejected/masked; (ii) `/api/tables` and `column_settings.profiles` omit hidden columns; (iii) export contains no hidden column and masked dates; (iv) Aurora join keyed on a hidden column fails; (v) MCP `open_dataset`+`query_dataset` and Agent `inspect_table` see the policy view; (vi) same SQL under two policy digests gives different cache keys; (vii) `INSERT` through the read engine fails with `25006`; (viii) a saved view with pre-policy SQL is re-validated on open.

Milestone 2: row predicates (site/consent) and DuckDB-staged copies. Milestone 3: platform-backed per-audience resources.

## (d) Open questions for the Workbench platform team

1. Does the app proxy forward a verified caller identity to the container, and can a non-owner ever reach an app's proxy URL?
2. Which DDL can `_rw` run: `CREATE ROLE`, `CREATE POLICY`, `ENABLE/FORCE ROW LEVEL SECURITY`, `security_invoker` views, `ALTER DEFAULT PRIVILEGES`? Only `GRANT/REVOKE` rejection is documented.
3. Does `_ro` automatically see tables created by `_rw` (default privileges), and can its visibility be narrowed per schema/column? Are per-group DB roles or per-user IAM tokens on the roadmap?
4. `PRIVATE_ACCESS` Aurora semantics: distinct DB user per private resource; can two resources map to one database with different privileges?
5. Can data collections include AWS Aurora/S3, and can a group policy restrict a single schema/resource within a workspace?
6. Is there an audit trail of who resolved which Aurora credential?
