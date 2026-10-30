# Select code and dependencies separately

1. Source pins are candidates; only the weekly lock reaches prod. This tool exports host versions and existing OCI digests for the private verily1 weekly check.
2. Export with `node startupscript/butane/dependency-lock.mjs export . host.json lock.json`; `host.json` provides `host_versions` and `host_artifacts` for Flatcar, Compose, Buildx and NVIDIA, using each download's HTTPS URL and SHA256.
3. Node and the CLI default to this source's pins; explicit host versions/artifacts override those defaults, and the CLI keeps its native `package.json` and `package-lock.json` together.
4. The launcher injects the selected lock at `/home/core/dependency-lock.json`; boot selects Node/CLI and rewrites existing image/feature digests before parsing or building first-party apps; custom app repositories keep their own container dependencies while using the selected host pins.
5. `node startupscript/butane/dependency-lock.mjs validate lock.json` checks the schema; `apply-host lock.json HOST_DIR` selects installed host scripts, and `apply ROOT lock.json [HOST_DIR]` rejects new, missing or conflicting covered references before changing files.
6. `startupscript/butane/dependency-lock-contract.json` identifies compatible source revisions; verily1 validates the exact source SHA separately from the lock.
7. Floating in-container installs and mutable references outside this lock remain unpinned risks; no packages are stored, mirrored or replayed.

Run `bats scripts/test/dependency-lock.bats` for selection, hotfix and contract-failure tests; the existing script-test workflow runs them on PRs.
