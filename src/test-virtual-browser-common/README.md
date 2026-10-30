# TEST virtual-browser apps (airlock canary)

The `src/test-virtual-browser-jupyter` and `src/test-virtual-browser-rstudio`
apps are test-only copies of the production virtual-browser apps, used by the
Workbench e2e canary that verifies airlocked (deny-all network) workspaces:
direct egress is blocked while package installs still work through the
Workbench mirrors.

The production apps expose only a pixel stream through the app proxy, so the
canary cannot drive them from the outside. Instead, these copies add a small
background runner (`airlock-matrix-runner.sh`) to the same containers. The
runner coordinates with the e2e test through an S3 storage folder in the
workspace named `airlock-matrix-folder`:

1. The test creates the folder, then the app, and waits for the airlock
   security group to be applied.
2. The test uploads an `airlock-go` marker to the folder.
3. The runner, polling for that marker, runs the egress/install matrix and
   uploads `airlock-matrix-results-<variant>.txt` and an
   `airlock-matrix-done-<variant>` marker, which the test reads and asserts.

## Keeping the copies in sync

Everything except `docker-compose.test.yaml` and the runner is **generated**
from the production app folders. The VM bootstrap substitutes
`${templateOption:*}` placeholders only in files inside the app's own folder,
so the compose files must be copies rather than cross-folder references.

After changing `src/virtual-browser-jupyter`, `src/virtual-browser-rstudio`,
or this folder, regenerate:

```sh
python3 src/test-virtual-browser-common/generate.py
```

CI runs `generate.py --check` and fails the build if the generated copies
have drifted.
