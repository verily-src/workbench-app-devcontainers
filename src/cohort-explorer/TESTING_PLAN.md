# Cohort Explorer Testing Plan

Goal: stop the entropy loop. Every commit runs machine checks that would have caught the regressions we've already hit.

## Phase 1 — Pre-commit hook (immediate, blocking)

### Mechanism

**Raw `.git/hooks/pre-commit` shell script**, versioned as `src/cohort-explorer/scripts/pre-commit.sh` and installed by `src/cohort-explorer/scripts/install-hooks.sh`.

Rejected alternatives:
- **`pre-commit` framework (Python pkg)** — adds a dep, YAML config, and network fetch for hooks we already own. Overkill for two commands.
- **husky** — bootstraps only from `package.json`. Backend contributors would need npm just to install a Python-adjacent hook.

Trade-off accepted: raw script means Windows contributors need Git Bash / WSL. Acceptable — the app only runs on Linux containers anyway.

### Install (one-liner)

```bash
bash src/cohort-explorer/scripts/install-hooks.sh
```

Script symlinks `.git/hooks/pre-commit` → `../../src/cohort-explorer/scripts/pre-commit.sh` (relative from `.git/hooks/`) and chmods +x. Idempotent. Prints a one-line reminder to add it to onboarding.

### Hook logic

```bash
#!/usr/bin/env bash
set -euo pipefail
REPO=$(git rev-parse --show-toplevel)
CE="$REPO/src/cohort-explorer"

CHANGED=$(git diff --cached --name-only --diff-filter=ACM || true)
touches() { echo "$CHANGED" | grep -q "^$1"; }

FE=0; BE=0
touches "src/cohort-explorer/frontend/" && FE=1 || true
touches "src/cohort-explorer/app/"      && BE=1 || true

if [ "$FE" = 1 ]; then
  [ -d "$CE/frontend/node_modules" ] || { echo "run 'npm ci' in $CE/frontend first"; exit 1; }
  (cd "$CE/frontend" && npx tsc --noEmit) || exit 1
  (cd "$CE/frontend" && npx vitest run --reporter=dot) || exit 1   # Phase 2 addition
fi

if [ "$BE" = 1 ]; then
  python3 -c "import fastapi" 2>/dev/null || {
    echo "run 'pip install -r $CE/app/requirements.txt' first"; exit 1; }
  (cd "$CE/app" && python3 -c "from main import app") || exit 1
  (cd "$CE" && python3 -m pytest app/tests -m "not slow" -q) || exit 1  # Phase 2 addition
fi
```

Phase 1 delivers only the `tsc --noEmit` + `from main import app` lines. The `vitest` / `pytest` lines land in Phase 2 once tests exist.

Bypass with `git commit --no-verify` — allowed for docs-only fixes; the hook already skips when no frontend/app files are staged.

## Phase 2 — Unit tests

### Framework choices

- **Backend**: `pytest` + `pytest-asyncio` + FastAPI's `TestClient` (starlette). Add to `app/requirements-dev.txt` (new): `pytest>=8`, `pytest-asyncio>=0.24`, `httpx>=0.27` (TestClient dep). Justification: standard, zero learning curve.
- **Frontend**: **keep vitest** — already installed, already has `api.test.ts`, `chartData.test.ts`, `ConnectionError.test.tsx`. No reason to switch.

### File layout

```
src/cohort-explorer/
  app/
    tests/
      __init__.py
      conftest.py           # sys.path shim + in-memory SQLite fixture
      test_schema_infer.py
      test_dynamic_model.py
      test_workflow_rows.py
      test_seed.py
      test_api_smoke.py
      fixtures/
        tiny.tsv            # 20 rows, covers empty-first-N-rows case
        all_numeric_text.csv
  frontend/src/
    *.test.ts / *.test.tsx  # colocated (existing convention)
```

`conftest.py` prepends `app/` to `sys.path` so tests can `from main import app` without packaging. Uses SQLAlchemy `create_engine("sqlite:///:memory:")` per-test; each test that touches DB clears `DynamicBase.metadata` and rebuilds. No `wb`, no S3, no Aurora, no threads.

### Taxonomy — which tier runs where

**Pre-commit (fast, <5s total, no I/O beyond in-memory SQLite):**
- All backend tests marked `not slow` (default marker).
- All frontend vitest tests (already sub-second).

**CI / manual only (`pytest -m slow`):**
- Full FastAPI startup with real SQLite file.
- Subprocess-mocked `wb` calls in `db.py` / `cohorts.py`.
- Multi-step scenarios (seed → confirm schema → query → export).

Mark slow tests with `@pytest.mark.slow` and add `markers = slow: excluded from pre-commit` to a new `pytest.ini`.

### Initial test list — 8 tests, mapped to regressions

| # | Test | Regression it catches | Tier |
|---|------|-----------------------|------|
| 1 | `test_workflow_rows_skips_when_cohort_col_null` — build rows for samples where one has None in a bound cohort column; expect that row omitted. | `_build_salmon_row` NULL-column skip logic — now the same bug lives in `_build_workflow_rows` (`main.py:697-711`). | fast |
| 2 | `test_dynamic_model_preserves_column_order` — `set_active_mapping([{col:"gtex_sample_id"...}, {col:"dbgap_sample_id"...}])`, assert `get_all_columns()[0] == "gtex_sample_id"`. | `_find_column` used sorted `dir(model)` and grabbed `dbgap_*` before `gtex_*`. Enforces list-order semantics. | fast |
| 3 | `test_dynamic_model_recreate_drops_stale_columns` — set mapping A, drop/create tables, set mapping B (different column set), assert new model has only B's columns and old PK is gone. | Stale `data` table with `_rowid` PK after schema change. | fast |
| 4 | `test_schema_infer_all_numeric_text_is_float` — CSV column with values `["1.2","3.4","5.6"]` returns `type="float"`, not `"text"`. | Text-with-numeric-values misinferred; review UI let float be picked, comparisons broke. | fast |
| 5 | `test_schema_infer_sees_columns_empty_in_first_1000_rows` — fixture where col X is empty rows 1-1200, populated rows 1201-1400. With default `sample_size=5000`, X is typed correctly (not defaulted to text). | `SMATSSCR`-style late-populated column bug. | fast |
| 6 | `test_api_samples_500_returns_detail_body` — force `_get_model()` to raise, TestClient GET `/api/samples`, assert 500 response has JSON `{"detail": "..."}` and detail is non-empty. | Bare "Internal Server Error" required container log spelunking. Same test for `/api/filters`. | fast |
| 7 | `test_seed_dynamic_handles_sentinel_values` — TSV with `NA`, `""`, `.`, `null` in various columns; assert corresponding DB cells are None, not the literal string. | `SENTINEL_VALUES` handling in `seed.py`. | fast |
| 8 | Frontend `SchemaReview.test.tsx` — mount with `mappings=[{type:"float",...}]`, user changes type to `"integer"`, click Confirm, assert `confirmSchema` is called with the mutated mapping (not the initial prop). | `useState`-based state that only populated on user click, missed mount-time auto-selection defaults. Regression pattern: initial-vs-current state divergence. | fast |

Not yet — add after these prove value:
- `test_build_workflow_rows_static_only` (workflow rows work with only static bindings — --inputs replacement).
- `test_api_filters_with_null_option` (`__null__` sentinel round-trip).
- `test_cohort_save_load_roundtrip` (in-memory only; skip S3).

### Explicit non-goals

Do NOT write tests for:
- `wb` CLI invocations (`_fetch_resources`, `resolve_connection_string`, `_ensure_workspace`, `_fetch_wdl_inputs`) — mocking subprocess is high-effort, low-signal. Rely on runtime.
- Live Aurora connections (`infer_from_aurora`, `_connect_aurora`) — needs psycopg + network.
- S3 uploads/downloads (`_fetch_s3_files`, `_save_to_s3`, `_resolve_path` with `s3://`).
- Background threads / cache warming (`warm_resource_cache`, `_warm_s3_files`).
- Startup workspace/AWS-config resolution (env + EC2 metadata).
- Docker build and container hot-patch flow.
- Full browser end-to-end (Playwright/Cypress) — out of scope for now.
- Actual workflow submission (`_run_workflow_in_background`).

These fail in real environments in ways unit tests won't catch anyway. The pre-commit gate + fast unit suite + human runtime verification is the intended safety net.

### Sequence of work

1. Write `scripts/pre-commit.sh` + `scripts/install-hooks.sh`. Install locally, commit. **Ship immediately** — this is Phase 1.
2. Add `app/requirements-dev.txt` and `app/tests/conftest.py` + `pytest.ini`.
3. Write tests 1-7 in order; each should fail on a synthetic reintroduction of the regression, then pass on current code.
4. Write test 8 in frontend using `@testing-library/react` (already installed) + `vi.mock('../api', ...)`.
5. Uncomment the vitest + pytest lines in the pre-commit hook.
6. Add `make test` target (optional) that runs both suites, for humans who want one command.

### Owner action items

- Decide: should the hook `git stash --keep-index` before checks so unstaged changes don't leak in? Recommendation: yes for backend (import test picks up unstaged code) but adds fragility. Defer to first bug report.
- Decide: run tests on files outside `src/cohort-explorer/` if only docs change? Recommendation: no, hook already skips when neither frontend nor app is touched.
