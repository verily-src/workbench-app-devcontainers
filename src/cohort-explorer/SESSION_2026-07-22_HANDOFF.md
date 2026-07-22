# Cohort Explorer — Handoff (2026-07-22)

Branch: `BENCH-8640-cohort-explorer`. Latest commit: `c793e2a`.

## State

The app is datasource- and workflow-agnostic and functionally complete. Read `README.md` (just updated) for the full feature + architecture picture. This doc covers what happened this session and what's still open.

## What shipped this session (newest first)

| Commit | What |
|--------|------|
| `c793e2a` | README rewrite (dynamic schema, S3 loading, workflow-agnostic, testing) |
| `2e8fce1` | EC2 `WorkspaceId` tag fallback in `_ensure_workspace()` |
| `5d05c70`, `838e061`, `1f697c5` | pytest infra + first 3 unit tests |
| `4e2474c` | `.gitignore` + remove committed `__pycache__` |
| `feea941` | pre-commit hook (`scripts/pre-commit.sh`, `install-hooks.sh`) |
| `e6919a6` | `_ensure_workspace()` at startup (env-var version) |
| `77d3cc9` | Workflow-agnostic job submission (RunWorkflowDialog replaces RunSalmonDialog) |
| `fba80f8` | Numeric-in-text type inference (90% threshold, Aurora text reclassification) |

## The workspace bug (root-caused this session)

**Symptom:** fresh apps fail with `There was an error in the VM Startup Script on line 1, command "source"`, and/or the datasource selector is empty ("No workspace set").

**Root cause:** during the VM's postCreateCommand, `install-cli.sh` runs `wb workspace set` (prints "Workspace successfully loaded"), but the workspace does **not** persist to `context.json`. The very next script, `setup-bashrc.sh`, calls `wb workspace describe`, gets "No workspace set", and the `source` fails → whole startup tagged ERROR. Verified in `/root/.workbench/post-startup-output.txt` on a failing VM. `wb` itself works fine when run manually against the same container — the failure is specific to the fresh-boot path, correlated with SAM latency (calls that normally take ~2-5s were taking ~20s).

**This is a platform bug in `startupscript/` (repo root), not our app.** Worth filing upstream with that log as evidence.

**Our workaround (`2e8fce1`):** `_ensure_workspace()` runs at uvicorn startup and, if no workspace is set, discovers the UUID from the EC2 `WorkspaceId` instance tag via IMDSv2 and runs `wb workspace set --uuid=`. This self-heals the app even when the postCreateCommand failed. Note: it runs at **uvicorn startup**, so the VM may still show the ERROR screen from the failed postCreateCommand, but the app container comes up and works. Confirmed IMDS is reachable from inside the container.

### Fixing an already-broken instance

Hotpatch to the fixed main.py, then restart uvicorn (self-heals via EC2 tag):
```bash
sudo docker exec application-server bash -c 'curl -fSL "https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/BENCH-8640-cohort-explorer/src/cohort-explorer/app/main.py" -o /app/main.py && pkill -f uvicorn'
```
Or manually: `sudo docker exec application-server wb workspace set --id=<workspace-id>` then `pkill -f uvicorn`.

## Open items / next steps

1. **Verify the workflow-agnostic flow end-to-end in a fresh app.** Committed but never fully exercised in a running app. Check: workflow picker lists all registered workflows; picking one populates the WDL input table; cohort-column vs static binding works; submit writes the batch CSV + mapping JSON to S3 and creates runs. Salmon is the regression check; a scalar-`File` workflow (fq2bam / merge_fastqs, if found) is the clean demo.
2. **`Array[File]` inputs can't bind to cohort data** (e.g. Salmon `input_files` needs `[fastq1, fastq2]` combined). No single column holds that shape; multi-column-to-array binding is unbuilt. Accepted for now — demo with a scalar-File workflow.
3. **Finish Phase 2 tests.** 3 of ~8 planned written (see `TESTING_PLAN.md`). Remaining high-value ones: `_build_workflow_rows` NULL-skip, drop-stale-table on schema recreate, `/api/samples` 500-returns-detail, seed sentinel handling, SchemaReview mount-state. Then wire pytest+vitest into the pre-commit hook (lines are stubbed in `scripts/pre-commit.sh`).
4. **wb-mcp server** now registered for Claude Code (user settings `allowedMcpServers` includes `http://127.0.0.1:9242`). Next session launched via `claude --resume` will have the 108 Workbench MCP tools — use those instead of shelling out to `wb`. If the server process died: `nohup /opt/wb-mcp-server/wb-mcp-server -http -port 9242 &> /tmp/wb-mcp-server.log &`.
5. **`samples` view is undocumented DDL.** It was created interactively in Aurora (`gtex-public-cohort-db-west`), never committed. `AURORA_SETUP.md` (reverted, commit `59a0091`) creates the `gtex_sample_attributes` table but not the view. Consider committing `SELECT pg_get_viewdef('samples'::regclass, true)` output as a setup script.

## Key context files

- `README.md` — features + architecture (current)
- `TESTING_PLAN.md` — Phase 1 (done) + Phase 2 test plan
- `WORKFLOW_AGNOSTIC_PLAN.md` / `workflow-agnostic-design.md` — the workflow-agnostic design + Workbench-source evidence
- `/home/jupyter/parked-workspace-fix.patch` — now APPLIED (commit `2e8fce1`); patch file can be deleted

## Guardrails (learned the hard way this session)

- Backend `.py` is hotpatchable (`curl` + `pkill uvicorn`); frontend needs a full rebuild / new app.
- Nearly every failure this session traced back to one of: `wb` needs a workspace set; `aws s3` needs `--profile <resource_id>`; the 60s proxy timeout on slow `wb`/`aws` calls (fixed with caching + pre-warming); or SAM latency. Check those first before adding code.
- Don't stack patches on symptoms — we burned a lot of turns in "entropy loops." Root-cause first.
