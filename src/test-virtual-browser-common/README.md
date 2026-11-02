# TEST virtual-browser apps (airlock canary)

`src/test-virtual-browser-jupyter` and `src/test-virtual-browser-rstudio` are
test-only copies of the virtual-browser apps. An e2e test uses them to check
that airlocked (deny-all network) workspaces block direct egress while package
installs still work through the Workbench mirrors.

The virtual-browser apps expose only a pixel stream, so the copies add a
background runner (`airlock-matrix-runner.sh`). It talks to the test through a
workspace S3 folder named `airlock-matrix-folder`:

1. The test creates the folder and the app, and waits for the airlock.
2. The test uploads an `airlock-go` marker.
3. The runner runs the matrix and uploads
   `airlock-matrix-results-<variant>.txt` and an
   `airlock-matrix-done-<variant>` marker.

## Keeping the copies in sync

Everything except `docker-compose.test.yaml` and the runner is generated from
the production app folders. The VM bootstrap fills in `${templateOption:*}`
only in files inside the app's own folder, so the files must be copies.

After changing either virtual-browser app or this folder, regenerate:

```sh
python3 src/test-virtual-browser-common/generate.py
```

CI runs `generate.py --check` and fails if the copies have drifted.
