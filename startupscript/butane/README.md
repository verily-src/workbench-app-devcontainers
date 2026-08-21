# Scripts to be mounted through ignition scripts to workbench-provisioned VMs.

The directory contains scripts that set up `devcontainer` apps inside workbench-provisioned VMs.

## Logging

`run-fluent-bit.sh` runs [Fluent Bit](https://fluentbit.io) on the VM with `aws/fluent-bit.conf` or
`gcp/fluent-bit.conf`, forwarding two kinds of logs:

| Fluent Bit tag | Source                                                          |
| -------------- | --------------------------------------------------------------- |
| `vm.journal.*` | systemd units (startup, docker, idle shutdown, proxy, stats, …) |
| `vm.docker`    | stdout/stderr of **every** container on the VM                  |

On AWS the records go to the CloudWatch log group `/aws/ec2/app-instance/<instance-id>`, one stream
per tag (`<instance-id>-vm.docker`, `<instance-id>-vm.journal.startup`, …). On GCP they go to Cloud
Logging as `gce_instance` records.

### Container log fields

All containers share the `vm.docker` tag, so each record carries fields identifying where the line
came from:

| Field            | Example                                              | Notes                                  |
| ---------------- | ---------------------------------------------------- | -------------------------------------- |
| `container_name` | `application-server`, `jupyterlab`, `proxy-agent`    | Added by `container-name.lua`          |
| `container_id`   | `9af8b280f743`                                       | Short id, as shown by `docker ps`      |
| `log`            | `[I 2026-01-01 10:00:00.000 ServerApp] 200 GET /...` | The log line itself                    |
| `stream`         | `stdout` or `stderr`                                 |                                        |
| `filepath`       | `/var/lib/docker/containers/<id>/<id>-json.log`      | Source file on the VM                  |
| `severity`       | `INFO`, `WARNING`, `ERROR`, …                        | Added by `severity.lua`                |
| `time`           | `2026-01-01T10:00:00.000000001Z`                     | Timestamp the container wrote the line |

`container_name` comes from the `tag` attribute that the Docker `json-file` log driver adds to every
line, because `/etc/docker/daemon.json` on the VM sets `"log-opts": {"tag": "{{.Name}}"}`. When a
container is started with its own `--log-opt` flags — which **replace** the daemon defaults rather
than merging with them — the name is instead read from
`/var/lib/docker/containers/<id>/config.v2.json` and cached per container.

Filter on `container_name` to look at one container. For example, on a VM whose app is split into a
front-end container and a JupyterLab container, `container_name = "jupyterlab"` selects the Jupyter
server's log, including its per-request access log lines.

### Severity

Journal records carry a syslog `PRIORITY`, which maps directly onto `severity`. Container logs have
no such field, so `severity.lua` derives it from level markers at the start of the line (`[E ...` /
`ERROR ...` / `WARNING ...` and friends) and falls back to `INFO`. This is best effort: a line whose
logger does not emit a recognizable prefix stays `INFO`, so `severity` is useful for narrowing a
search but is not a substitute for reading the messages.

### Known limitations

- `Skip_Long_Lines On` in the container log input means individual lines longer than the input buffer
  are dropped rather than truncated, so very long single-line output (e.g. a wide dataframe dump) may
  be missing from the forwarded logs.
- Containers that set their own Docker log options lose the daemon's default log tag; the fallback
  lookup covers this, but only while the container still exists on the VM.
