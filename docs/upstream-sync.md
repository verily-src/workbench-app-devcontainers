# Syncing upstream devcontainers

This repo keeps internal additions on top of
`verily-src/workbench-app-devcontainers:master`. Use a Git merge to retain both
histories. Do not copy the upstream tree over this repo or reset internal master.

## Scheduled sync

`.github/workflows/sync-upstream.yaml` runs every Monday at 08:23 UTC and supports
**Run workflow**. It checks out internal `master`, fetches upstream `master`, and:

- Does nothing if upstream is already an ancestor of internal master.
- Waits for review if an open `automation/sync-upstream-*` PR exists.
- Opens a PR targeting internal `master` if the merge succeeds.
- Fails with conflict paths in the run summary if manual resolution is needed.
  Nothing is pushed in that case. Authentication or other Git failures also fail
  the run; inspect the logs if the conflict list is empty.

It never automatically merges a PR or force-pushes. Review and CI still matter
even when Git can combine the files without conflicts. Watch failed workflow
runs for conflicts; the workflow does not create issues or send separate alerts.
If a push succeeds but PR creation fails, use the branch shown in the logs to
open the PR manually before retrying.

### One-time setup

1. Configure the Actions secret `SYNC_UPSTREAM_TOKEN` with an organization-approved
   token. It needs Contents read access to upstream and Contents read/write plus
   Pull requests read/write access to this repo. Because merges can change
   `.github/workflows`, grant the credential the corresponding workflow-write
   permission too. Authorize organization/SSO access where required. A fine-grained
   PAT can be scoped to these two repositories. Follow organization token policy.
2. Put the workflow on the repository's **default branch**. Cached metadata during
   setup pointed to `main`, while the application code lives on `master`. Verify
   in GitHub Settings. Either maintain the workflow on the actual default branch,
   or have a maintainer intentionally change the default to `master`. Merging
   this PR into a non-default `master` alone does not activate the schedule.
3. Run it once manually and confirm the PR's existing CI starts. The ordinary
   `GITHUB_TOKEN` is not used: it is scoped to this repository and its events
   generally do not trigger subsequent workflows. The supplied PAT allows the
   normal PR checks to run, subject to organization policies.
4. Require review and CI, then merge sync PRs using **Create a merge commit**.
   Squashing/rebasing discards the upstream ancestry needed by later syncs.

References: [scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
and [workflow token authentication](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token).

## Manual sync or AI-agent handoff

1. Verify the checkout and `git status --short`. Preserve existing work and
   untracked files. Start from internal `origin/master`, not a demo/feature branch
   and not the placeholder `main` branch.
2. Verify `origin` is `verily-src/vwb-eng-workbench-app-devcontainers`. Set
   `upstream` to `verily-src/workbench-app-devcontainers` if absent, or verify the
   existing remote before using it:

   ```bash
   git remote -v
   # Only if upstream is absent:
   git remote add upstream git@github.com:verily-src/workbench-app-devcontainers.git
   git fetch origin
   git fetch upstream
   git switch --no-track -c psu/sync-upstream-YYYYMMDD origin/master
   git merge --no-commit --no-ff upstream/master
   ```

3. Resolve each conflict based on behavior and history. Do not blindly choose
   ours/theirs. Check internal skills, dependencies, app startup configuration,
   and image pins. On a clean merge, inspect the automatically merged files too.
   If upstream is already included, stop; no sync commit is needed.
4. Validate the affected components. Useful checks include:

   ```bash
   git diff --name-only --diff-filter=U
   git diff --cached --check
   (cd features/src/wb-mcp-server && go test ./...)
   docker compose -f src/dc-access-logging-app/docker-compose.yaml config --quiet
   bash -n features/src/llm-context/generate-context.sh features/src/wb-mcp-server/install.sh
   ```

   The first command must produce no paths. Go currently has no test files, so
   that check establishes compilation only. Run relevant container/integration
   tests for runtime changes, and report any checks that could not run.
5. Stage only intended conflict resolutions, commit the merge, and verify
   `git merge-base --is-ancestor upstream/master HEAD`. Review the difference
   from both parents. Publish a PR to internal `master` when authorized; use a
   merge commit when accepting it.
6. Leave a short handoff with repo path, branch, both source SHAs, merge SHA,
   conflict decisions, tests, limits, and next action. Include the conversation
   ID if available. If using cached refs because fetching failed, say so clearly
   and refresh both remotes before publishing.

## Last local sync

On 2026-09-16, branch `psu/sync-upstream-master-20260916` merged internal
`8ecf68951970e57a75f7337290515c470c2caa7e` with upstream
`924f944aa8155d23fa8517219e12ee4b5090ac7a` in commit
`d302e5e1e5d9efd3d70a2ca2dbe0a788d4d52a4d`.

Four conflicting files took the upstream versions: MCP `main.go`, access-logging
`app.py` and `docker-compose.yaml`, and the Jupyter-with-LLM Dockerfile. Internal
Nextflow/WDL skills, PostgreSQL client installation, and style assets were kept.
GitHub DNS was unavailable, so the source revisions came from cached remote refs.
Go compilation, Compose validation, and shell/Python syntax checks passed; live
container tests were not run. Three Dockerfile whitespace warnings and two
Python escape warnings were inherited. No push was performed during that sync.
