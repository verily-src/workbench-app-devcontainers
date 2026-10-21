# Join branch comparison

Reviewed 2026-10-21: Studio `a0d90f3` against
[`yp-cohort-explorer-joins` at `4d25d21`](https://github.com/verily-src/workbench-app-devcontainers/tree/4d25d217291de0dd47bdeea6128ca3b5edc863d7/src/cohort-explorer).
The initial comparison was a static review. The five adaptations below are now implemented in Studio; validation and review results are tracked in PROJECT_STATE.md. No Explorer stack was copied.

## Useful gaps

| Priority | Capability | Evidence and proposed adaptation |
|---|---|---|
| High | Full-database exploration of joined data | Explorer maps a joined SELECT as a live subquery (`app/dynamic_model.py`, `set_active_join_mapping`). Studio joins in Aurora where possible, counts the full result, then loads at most 100,000 rows (`app/joins.py`, `_run_aurora`; `app/main.py`, `join_datasets`). Later Explore filters/charts use that loaded frame. Keep a validated join definition as a queryable source; run filters/aggregations on Aurora and limit only displayed rows. OMOP Count already queries the full database; this gap concerns Explore. |
| High | Distinct entity count after joins | Explorer's SchemaReview selects `entity_column`; `/api/counts` returns `count(distinct(...))`. Studio's generic query summary returns row counts. Add an explicit entity column, e.g. person_id, with row and unique-person totals under filters. Do not infer that every row is a person. |
| Medium | Restore a joined source | Explorer persists its active join SQL/resource/mappings in `active_schema.json` and restores them. Studio's join tab has no `sourceRef`, so SavedViews excludes it. Persist validated structured join recipes using durable resource/table IDs, not session dataset IDs or unchecked SQL. This also supports replay after in-app Update clears memory. Explorer only demonstrates local active-source restoration, not a multi-view repository. |
| Medium | Review column types, filter kinds and labels | Explorer has a SchemaReview UI and distinct storage/logical types, including text-backed numerics. Studio profiles loaded dtypes automatically; derived columns are not a schema review flow. Add explicit overrides and keep database decoding types separate. Test numeric-looking text with the real PostgreSQL driver. |
| Low | One shared key across selected tables | Explorer's JoinBuilder offers a common-column selector for all tables. Studio already defaults and suggests keys per step. Add an optional apply-to-all selector without replacing multi-condition joins. |

## Already covered or stronger in Studio

Studio has searchable join inputs, validation, growth previews and fan-out
warnings. It supports inner/left/right/full/semi/anti joins, multiple comparison
conditions, output-column selection, up to six steps, and cross-source DuckDB
fallback. The comparison branch offers three tables in its UI, three join types,
and one equality key per step over Aurora tables. Both generic Aurora table
lists are scoped to `public`; the branch does not solve schema browsing.

Do not port the whole Explorer stack. Its synthetic ORM row ID fixes ORM
identity-map deduplication; Studio's DataFrame result path does not share that
failure mode. Port the product behavior into Studio's source and query model.

## Proposed order and checks

1. Add distinct-entity counts and the common-key convenience control.
2. Define durable joined-source recipes and restore them through Saved Views.
3. Add Aurora-backed filter/aggregate execution for those sources.
4. Add schema overrides with storage/logical type separation.

Before shipping, use browser/API flows against real PostgreSQL to verify a
one-to-many join preserves all rows while counting each person once, filters
can match records beyond row 100,000, and saved joins reopen after a restart.
These checks are release requirements. See architecture.md for adopted decisions. Live compare, derive and chat remain unavailable; cross-resource queries still use loaded data.
