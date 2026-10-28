# Plan: separate airlock logic from the generic startup scripts

## Problem

The butane startup pipeline is generic — it runs every Workbench app type. Airlock
(the local-snapshot restore flow for apps with
`customizations.workbench.AIRLOCK_ENABLED`) started as one branch in
`devcontainer.sh` and has spread into inline branches across five generic scripts:

| File | Airlock knowledge |
| --- | --- |
| `devcontainer.sh` | `AIRLOCK_ENABLED` parsing, snapshot detection, `prepare_airlock`, skip-build branch, setup marker, `docker commit` |
| `container-utils.sh` | `validate_airlock_snapshot` |
| `050-parse-devcontainer.sh` | skip OCI feature prefetch when a snapshot exists |
| `060-start-proxy-agent.sh` | `validate_airlock_snapshot` call |
| `probe-proxy-readiness.sh` | `validate_airlock_snapshot` call (duplicate; removed separately) |

Each new airlock behavior requires editing shared scripts, and readers of the
generic pipeline must understand airlock to follow it.

## Design: lifecycle hooks with override files

Bash allows function redefinition: sourcing a later definition replaces an earlier
one. The pipeline declares its extension points once, as no-op functions, and
feature-specific override files redefine them.

- **`app-hooks.sh`** declares the hooks with no-op defaults, then sources every
  file in `overrides.d/`:
  - `app_prepare <config_path> <config_json> <primary_container_id>` — before
    devcontainer build/up.
  - `app_build_cached` — predicate: the app starts from a local image, so build
    and feature prefetch can be skipped.
  - `app_post_up` — after a successful `devcontainer up`.
  - `app_validate_setup [container]` — asserts setup completed; failing makes the
    calling systemd service retry.
- **`overrides.d/airlock.sh`** implements all four hooks. Enablement checks live
  inside the override: config-stage hooks read the `WB_APP_CUSTOMIZATIONS`
  environment variable (the `customizations.workbench` JSON object, exported by
  callers), and `app_validate_setup` reads the running container's
  `devcontainer.metadata` label. Every hook is a no-op for non-airlocked apps.

Generic scripts source `app-hooks.sh` and call hooks by lifecycle name only. The
string "airlock" no longer appears in any generic script.

## File changes

- `app-hooks.sh`, `overrides.d/airlock.sh` — new.
- `devcontainer.sh` — drops all `AIRLOCK_*`/snapshot variables and
  `prepare_airlock`; `build_app` and `start_app` call `app_prepare`,
  `app_build_cached`, and `app_post_up`. Exports `WB_APP_CUSTOMIZATIONS`.
- `container-utils.sh` — `validate_airlock_snapshot` moves to the override as
  `app_validate_setup`.
- `050-parse-devcontainer.sh` — the prefetch skip becomes `app_build_cached`.
- `060-start-proxy-agent.sh` — calls `app_validate_setup`; stays here (rather
  than a new unit `ExecStart`) because unit files are frozen into ignition at VM
  creation while scripts re-download each boot, so the check keeps working on
  existing VMs.
- `bootstrap-files.sh` — downloads the two new files.
- Tests (`scripts/test/container-utils.bats`,
  `scripts/test/integration/devcontainer.bats`) — target `app_validate_setup`
  via `app-hooks.sh`.

## Behavior preserved

- Non-airlocked apps: all hooks no-op; no snapshot inspection, no setup-state
  directory, `devcontainer up` exit codes propagate unchanged.
- Airlocked apps: same prepare/rewrite, skip-build, setup-marker, snapshot-commit,
  and validation semantics. Snapshot existence is now re-checked at each hook
  call instead of once at wrapper start; the value cannot change between those
  points within one invocation.
- Migration is atomic: every boot downloads all scripts from one commit of the
  pinned branch, and frozen unit files reference script paths, which do not
  change.

## Later (not in this change)

If a second app-type feature appears, the override-file convention already
supports it: add `overrides.d/<feature>.sh` gated on its own customization flag.
Hook granularity can grow as needed; prefer adding a hook over adding a feature
branch to a generic script.
