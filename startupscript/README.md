# Developer guide for (post)startup script

Verily Workbench provisions VMs post-creation to install workbench specific tools (such as CLI, gcsfuse, ssh-keys for git).

Currently there are three flavors of startup.script:

- vertex AI user-managed notebook
- dataproc cluster
- general gce instance (in the startupscript/ folder)

## How to test your change?

### Option 1

If it's a single line change, you can just create an environment in the devel environment and run the command.

### Option 2

If it's a complex change, you can point the VM to your new script and test it end-to-end.

#### Vertex AI

- Step 1

Make your change and push to a branch.

- Step 2

```text
wb resource create gcp-notebook --id=jupyterNotebookForTesting --post-startup-script=https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/<your-branch>/startupscript/vertex-ai-user-managed-notebook/post-startup.sh
```

- Step 3
  Go to the UI and wait till the notebook spins up and verify that it is running.

#### Dataproc

- Step 1

Make your change and push to a branch.

- Step 2

```text
wb resource create dataproc-cluster --name=dataprocForTesting --metadata=startup-script-url=https://raw.githubusercontent.com/verily-src/workbench-app-devcontainers/<your-branch>/startupscript/dataproc/startup.sh
```

Pick a workspace that you have previously created a dataproc cluster so you can reuse the buckets.

- Step 3
  Go to the UI and wait till the notebook spins up and verify that it is running.

#### GCE

- Step 1

Clone this repo and put it in a public repo you own. Make the change

- Step 2
  In the UI, create a custom rstudio app pointing at your personal repo.

- Step 3
  Wait for the notebook to spin up and go to the instance. Check .workbench/post-startup-output.txt to see if it succeeds.

## Linting and Style

Shell code in this repo will be checked with `shellcheck` as part of pull request testing.

The `shellcheck` tool [can be installed locally](https://github.com/koalaman/shellcheck?tab=readme-ov-file#installing).
Additionally, VSCode has a [ShellCheck extension](https://marketplace.visualstudio.com/items?itemName=timonwong.shellcheck).

To configure `shellcheck` locally with the same configuration as the PR lint tasks, create a
`~/.shellcheckrc` file with the following content:

```shell
disable=SC1090,SC1091
```

This disables checks [SC1090](https://www.shellcheck.net/wiki/SC1090) and
[SC1091](https://www.shellcheck.net/wiki/SC1091), to work around limitations in
`shellcheck` around dynamic file handling.

In addition to `shellcheck`-enforced logic, it is highly recommended that variables and functions
be made `readonly` to prevent overriding or unsetting.

For trivial variable assignment this can be done on a single line:

```shell
readonly FOO="foo"
```

However, for assignments that involve calling a command, `readonly` can mask error responses; in
these cases the variable should be marked `readonly` as a subsequent step.  This is enforced by
`shellcheck` rule [SC2155](https://www.shellcheck.net/wiki/SC2155).

```shell
FOO="$(command)"
readonly FOO
```

Functions follow this syntax:

```shell
function my_function {
    # ... function logic ...
}
readonly -f my_func
```

## General debugging tips

- Check /home/**\<user\>**/.workbench/post-startup-output.txt to see where the script failed.
  The user is jupyter for vertex AI, dataproc for dataproc cluster, and varies by app for gce instance.

- If the proxy url doesn't work, you can ssh to the VM.
