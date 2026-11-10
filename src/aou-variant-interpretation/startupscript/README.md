# startupscript/

This is a copy of the subset of `startupscript/` needed by `post-startup.sh`
at container runtime (`emit.sh`, `install-java.sh`, `install-cli.sh`,
`setup-bashrc.sh`, `gcp/vm-metadata.sh`), originally
copied from the upstream `verily-src/workbench-app-devcontainers` repo's
`startupscript/` directory (not vendored here -- see
[deploy/README.md](../deploy/README.md)). Upstream's git setup, bucket
mounting, restart remount and AWS scripts are intentionally not copied: VIA
only reads BigQuery, and they each added boot time (see `post-startup.sh`).

It exists here, at the repo root, because the Verily Workbench devcontainer
framework (`050-parse-devcontainer.sh`, fetched fresh from
`verily-src/workbench-app-devcontainers` on every VM boot) hardcodes
`/home/core/devcontainer/startupscript` -- i.e. it expects a `startupscript/`
folder at the root of whatever git repo gets cloned, and copies it into the
app's devcontainer folder (`deploy/`) before running `postCreateCommand`.
Since this repo's app code lives at the true root with the devcontainer
packaging vendored under `deploy/`, that copy has to live here instead.

If the upstream `startupscript/` changes in a way that matters for this app,
re-copy the relevant files here -- nothing keeps them in sync automatically.
