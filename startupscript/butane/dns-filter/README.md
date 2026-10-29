# dns-filter

Boot-time DNS allowlist for airlocked EC2 workspace instances (PHP-194237). Prevents DNS-based
data exfiltration: a security group alone cannot block traffic to the VPC's built-in DNS resolver.

Runs as its own container on the instance's default Docker bridge network, listening at
`172.17.0.1:53`. `dns-filter-setup.service` points the whole VM's Docker daemon at this address
(`/etc/docker/daemon.json`'s `dns` key) only on airlocked instances, before `docker.service` starts.

Two modes, selected by which config `wrapper.sh` (the container's entrypoint) starts dnsmasq
against:

- `open.conf` (default, at container start): forwards every lookup to the real AWS resolver, so
  package installs during devcontainer setup work normally.
- `allowlist.conf`: only the listed domains resolve; everything else gets NXDOMAIN.

Switching from open to restricted mode requires actually stopping and restarting dnsmasq -
reload signals don't apply changed `server=`/`address=` directives. `wrapper.sh` does this when
sent `SIGUSR1` (`docker kill -s SIGUSR1 <container>`), triggered by `probe-proxy-readiness.sh`
once devcontainer setup finishes.

`allowlist.conf` is currently hand-maintained - see the comment at the top of that file.
