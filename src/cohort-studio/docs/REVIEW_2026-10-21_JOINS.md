# Join improvements: review and release evidence

Date: 2026-10-21. Scope: the five useful behaviors identified in
[the Explorer comparison](JOIN_BRANCH_REVIEW.md).

## Delivered behavior

- Same-resource Aurora joins retain a server-compiled source for full-source
  counts, filters, chart aggregates, profiles and paged rows.
- Distinct non-null entity counts are explicit and separate from row counts.
- Saved views contain validated table/join recipes and column settings. They
  reopen after the in-memory dataset store is cleared. Client SQL is rejected.
- Column number/text, filter and label settings survive reload. Full-source
  numeric conversion rejects invalid or non-finite values outside the preview.
- One shared key can be applied to all selected join steps.

Production storage remains Aurora; internal loaded-data joins use DuckDB. There
is no standalone PostgreSQL deployment. Disposable PostgreSQL is only the local
Aurora-compatibility test fixture.

## Validation

- Production frontend build: passed.
- Browser E2E: six new cases passed (entity/settings, database-scope guards and
  refresh cancellation, shared keys, two large-loaded warning cases, and saved
  recursive join restore).
- Isolated release snapshot: **146 passed in 27.67 s**, with the unrelated local
  `app/db.py` override excluded. No tests skipped.
- Real-driver checks cover a 120,003-row joined result, a filter matching only
  late rows beyond the 100,000-row preview, distinct entities, histogram/bar
  totals, nested long column names, save/reopen, invalid conversions, adjacent
  large numeric IDs, and number→text changes that preserve padded IDs on reload.
- Exports fetch the full filtered result or reject the row cap. They never
  silently export only the preview. Compare, derive and chat reject live sources
  until they have full-source implementations.
- Live Aurora connectivity, Workbench runtime SHA and the browser-isolation
  sidecar remain unverified from this machine.

## Independent reviews

### Codex

A separate `codex review` process used `gpt-6-luna` with medium reasoning.
Its initial findings questioned the unfiltered chart reference series and empty
category selections. Both were checked against the existing pandas, DuckDB and
UI contracts: `all` is the reference population, `selected` is filtered, and an
empty selection clears a constraint. The follow-up review confirmed neither was
a regression and found no remaining blocker in the reviewed scope.

Transcripts: `/tmp/cohort-joins-codex-review.txt` and
`/tmp/cohort-joins-codex-final.txt`. A separate Codex subagent also reviewed the
source boundary and ran the focused compatibility checks; no blocker remained.

### OpenCode

OpenCode used `opencode/glm-5.3-flash-free`, variant `max`.
The first verdict was not release-ready. Its findings and disposition:

| Finding | Resolution |
|---|---|
| Missing category limit constant | Defined; full-source profile tests pass. |
| Numeric conversion required PostgreSQL 16 | Replaced with portable full-source CAST extrema validation and DataError handling. |
| Auto reset and label clearing were misleading | UI says Keep current; labels can clear; logical type is returned. |
| Compare validation returned 502 | Validation now returns 400. |
| Live pages lacked ordering | Added deterministic row ordering and a repeatable-read, read-only query snapshot. |

Final follow-up verdict: **approved; no release blockers found in the reviewed
join/settings scope**. The final settings review confirmed large-ID precision
and deterministic saved reload. Transcripts:
`/tmp/cohort-joins-opencode-review.jsonl` and
`/tmp/cohort-joins-opencode-verdict.jsonl`. The first follow-up stopped because
OpenCode disallowed reading an external temporary report; the successful retry
read only project files.

## Cache and warning addendum

The user then requested large-result warnings and caching. Explore now has a
30-second in-memory result cache with bounded entry/payload budgets, visible
fetch timestamps, a manual refresh, and resource invalidation after writes.
Exports bypass this cache. Refresh updates both results and filter profiles.
Large-source warnings preserve the distinction between complete loaded data,
capped previews and full-source Aurora queries.

Local database checks cover cache miss/hit, changed source rows, stale cached
counts, explicit refresh, updated category profiles, oversized results bypassing
the cache, and failures that are not cached. Codex (`gpt-6-luna`) found no blocker in the cache scope; OpenCode GLM max
approved the cache scope. The final browser/suite checks passed: **146 tests in 27.67 s**, no skips.
The final UI also clears refresh state after filter changes cancel a request,
and limits preview/cap wording to the cases where it applies. Review artifacts:
`/tmp/cohort-cache-codex-review.txt` and
`/tmp/cohort-cache-opencode-review.jsonl`.

## Support priorities and decisions

1. **Verify the actual dev environment next.** Run saved-join restore, a known
   count, export and in-app Update smoke checks inside Workbench with Aurora
   access. Confirm the running SHA and isolated-browser route. Local tests cannot
   prove cloud credentials or network access.
2. **Add streaming exports with progress and cancellation.** Keep the current
   explicit cap until a server cursor/COPY path can finish or fail atomically.
3. **Add full-source compare and derived columns.** Extend the existing validated
   query model before enabling those tools for live sources. Dataset chat should
   use bounded aggregate tools, not the preview as if it were the full source.
4. **Improve query cost and support diagnostics.** Add timings, cancellation and
   a redacted support report; evaluate keyset paging and combined aggregates with
   measured Aurora workloads. Current deterministic sorting can be expensive on
   large results and remains subject to the statement timeout.

These are the next priorities, not features claimed in this release. Do not add
AgentCore infrastructure or a Jev dependency before the existing runtime and
provider path are verified; their earlier scope documents still apply.
