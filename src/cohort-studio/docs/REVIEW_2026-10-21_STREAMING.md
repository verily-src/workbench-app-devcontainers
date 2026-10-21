# Streaming export and full-source tools

Date: 2026-10-21. Follows the published joins/cache release `3eca601`.

## Scope

Aurora-backed tabs now support Compare, derived columns and background TSV export.
Compare aggregates in Aurora; categorical results contain at most 22 bucket rows.
Exact Mann–Whitney values are fetched only for small, tie-free samples with at
most 10,000 combined rows. Other comparisons use SQL ranks and tie correction.
The residual category has a separate label from a real `Other` value.

Derived bin/formula/map operations use validated recipes and bound parameters.
Recipes reopen from their base source and retain parameters through joins,
queries and exports. Quoted SQL identifiers with colons are handled correctly.

Exports use server cursors, fresh database snapshots and private temporary files.
Only complete files can be downloaded. Cancellation interrupts the driver query;
failed and cancelled files are removed. The worker clears its connection handle
before returning it to the pool. See the README for time and disk limits.
The synchronous export, materialize and S3 workflow paths retain their row cap.

## Reviews

- Codex CLI, `gpt-6-luna`: follow-up found no blocker in the reviewed backend scope.
  Its initial claim that category results were unbounded was disproved by the SQL
  grouping and confirmed by the follow-up (maximum 22 rows).
- OpenCode: `opencode/glm-5.3-flash-free`, variant `max`; no release blocker
  found. Its narrow final review returned **PASS — no blocker**, verifying fixes for cancelling a completed file, pooled-connection
  lifetime and Compare's column-setting overrides. The reported `_debug` field
  was already absent. Failed-job row counts intentionally show processed rows;
  they are not a downloadable result. Nullable-integer map null labels can differ
  from pandas (`None` versus `<NA>`); this existing mapping edge remains a limit.
  The export cap change is intentional and recorded in architecture.md.
- Separate lower-cost Codex agents implemented and checked the database and
  browser outcomes. Final inspection found stale settings on overwritten derived
  columns and polling that stopped after repeated running states. Both are fixed
  and covered by database/browser outcomes.

Reports: `/tmp/cohort-next-codex-review.txt`,
`/tmp/cohort-next-codex-final.txt`, `/tmp/cohort-next-codex-last.txt`,
`/tmp/cohort-next-opencode-review.jsonl`, `/tmp/cohort-next-opencode-final.jsonl`.

## Evidence and limits

Initial complete local suite: **152 passed in 42.74 s**. Export cancellation
follow-up: **3 passed in 2.21 s**. Final isolated release snapshot: **152 passed
in 49.35 s**, no skips, with the unrelated local db.py override excluded.
Production frontend build and browser export progress/cancel/clear checks pass.
The local tests use disposable PostgreSQL as an Aurora driver compatibility
fixture. Production storage remains Aurora and the internal engine is DuckDB.

All dev Studio instances were stopped at the latest CLI check. No browser was
available. Actual Aurora, runtime SHA and browser-isolation validation remain
pending; code publication does not prove deployment.
