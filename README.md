# workbench-app-devcontainer

Repo to store Verily Workbench specific applications' devcontainer. To develop your own custom app configuration, clone this repo.

## What does Workbench specific applications require

1. the custom app runs in a custom `app-network` bridge network and the app port is exposed on 0:0:0:0 (localhost)
2. the app's container_name must be `application-server`
3. In order to run `gcsfuse`, set `--cap-add SYS_ADMIN --device /dev/fuse --security-opt apparmor:unconfined` to the docker container.

## What is devcontainer

https://containers.dev/

## How to use

The `.devcontainer.json` file in the custom app folder (e.g. r-analysis/) contains the custom app configuration.
`post-startup.sh` contains workbench specific set up.
