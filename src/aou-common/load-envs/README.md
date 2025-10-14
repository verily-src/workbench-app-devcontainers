# aou-jupyter JupyterLab App Image for All of Us

The JupyterLab App Image for All of Us. This image is built off of the latest
published [`app-workbench-jupyter`](../workbench-jupyter), image. Updates to
workbench-jupyter will not propagate to this image until the next build.

## Environment Variables

To add an environment variable set to the container, create a new directory in
[`envs`](./envs). The path to the env file should be
`envs/<data collection UUID>/<version name>.env`.

## Known Issues

- nvidia-smi does not recognize processes running in the container. See https://stackoverflow.com/questions/63203867/nvidia-smi-does-not-display-any-processes
