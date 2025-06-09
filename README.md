# workbench-app-devcontainer

Repo to store Verily Workbench-specific applications' devcontainer specifications. To develop your own custom app configuration, clone this repo.

## Workbench-specific application requirements

1. The custom app runs in a custom `app-network` bridge network and the app port is exposed on 0:0:0:0 (localhost)
2. The app's `container_name` must be `application-server`
3. In order to run `gcsfuse`, set `--cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined` to the Docker container.
4. If using a new Docker registry and/or adding new features, update the
   [firewall](https://github.com/verily-src/gcp-org-workbench-iac/blob/main/4-app-cache/firewall.tf)
   to allow new egress as needed.

## What is a dev container?

https://containers.dev/

## How to use

The `.devcontainer.json` file in the custom app folder (e.g. r-analysis/) contains the custom app configuration.
`post-startup.sh` contains workbench specific set up.

Please visit https://support.workbench.verily.com/docs/guides/cloud_apps/create_custom_apps for details about using a dev container specification to create a custom app in Workbench.
