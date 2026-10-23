# Custom SQL source security review

Review date: 2026-10-23. Scope: `sql_source.py`, `source_models.py`, open and
preview routes, plus the live query, join, compare, derive, settings, and export
paths that execute a saved SQL source.

## Verdict

No confirmed security blocker remains in the reviewed code after the fixes
below. The root agent is running the integration tests; this review did not run
the full suite.

## Confirmed findings and fixes

- The SQLGlot parser originally exempted any unqualified table whose name
  matched a CTE anywhere in the query. A nested CTE name could therefore
  exempt an out-of-scope `pg_class` reference, which resolved to
  `pg_catalog.pg_class`. `traverse_scope` now exempts only table nodes that
  resolve to a CTE in their lexical scope. The nested-scope bypass is rejected;
  ordinary and nested in-scope CTE references are accepted.
- Schema-qualified operators could bypass the function allowlist. The parser
  now rejects them. It also rejects user-defined cast types, which could invoke
  custom input or conversion functions outside the function allowlist.
- Live derived-column preview and logical-number validation initially ran
  without a read-only transaction or fixed search path. Both now set
  `REPEATABLE READ READ ONLY`, `search_path = pg_catalog`, and a statement
  timeout before querying a stored SQL source.

The SQL source boundary accepts one PostgreSQL `SELECT`, requires qualified
non-CTE table names, rejects DML/DDL, `SELECT INTO`, row locks, system schemas,
cross-database references, placeholders, table-valued functions, qualified
functions/operators, custom types, and functions outside its allowlist. SQL
preview/open normalizes the query before execution. Saved `SQLSource` refs use
strict Pydantic models and the same normalizer.

Preview/open execute in read-only PostgreSQL transactions. Stored SQL sources
continue through read-only transaction paths for profile, query, charts,
comparison, joins, derived previews, column settings, and exports. Those paths
also pin `search_path` to `pg_catalog` and set timeouts. Cache hits do not run
SQL. Reopen and saved-view round trips pass through SourceRef validation and
the SQL normalizer again.

## Review triage

Three external review claims were checked and were false in the current code:

- `nextval` and `set_config` are not in `_SAFE_FUNCTIONS`; they are rejected
  by normalization. Schema-qualified functions are rejected too.
- A hand-built `SQLSource` does not bypass resource access. It uses
  `db.get_engine_for_resource`, which resolves the same Workbench resource
  ID with `wb resource resolve` as the existing Aurora source path.
- A capped preview does not cap a same-resource live query or join. The
  initial frame is capped, while the normalized SQL remains in `live_source`
  for database-scoped queries. This is the established full-source semantics
  used by existing Aurora sources, not a SQL-specific expansion.

## Review checks

Direct parser checks against the reviewed code:

- Rejected: nested out-of-scope `pg_class`, `OPERATOR(public.+)`,
  `CAST('x' AS cdm.some_type)`, `nextval`, `set_config`, qualified
  `pg_catalog.set_config`, DML CTE, multiple statements, system-schema table,
  and `$1`, `:name`, and `?` placeholders.
- Accepted: normal arithmetic, built-in `LOWER`, built-in numeric/text casts,
  an in-scope CTE, and a nested in-scope CTE.
- `source_dict` accepted a strict valid SQL SourceRef and rejected the unsafe
  SQL and an unexpected field.

The committed focused integration coverage in `tests/test_sql_source.py`
checks preview, open, database-scoped query, same-resource join, and durable
source reopen over a 100,001-row PostgreSQL fixture, plus unsafe SQL rejection
and timeout mapping. The full integration suite result is tracked separately
by the root agent.

## External GLM review follow-up

OpenCode GLM max frontend review found no confirmed blocker. Backend review
found an unhandled RecursionError for deeply nested SQL; fixed with nesting,
token and query-node limits and validation errors. The review re-probed the
final code and found no remaining blocker. Logs: /tmp/cohort-ui-sql-glm.jsonl
and /tmp/cohort-sql-backend-glm.jsonl. Local container testing also exposed a
join key edit racing source loading; key edits and join execution are now
disabled while a source loads. Final integration results belong in PROJECT_STATE.
