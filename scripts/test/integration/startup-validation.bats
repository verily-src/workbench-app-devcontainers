#!/usr/bin/env bats
# Run the production proxy-start and readiness scripts with controllable
# setup/snapshot and frontend state. No cloud or registry access is needed.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../.." && pwd)"
    CORE="${BATS_TEST_TMPDIR}/core"
    mkdir -p "${CORE}/bin" "${CORE}/container-state.d/setup"
    printf 'STARTED\n' > "${CORE}/status"
    printf 'true\n' > "${CORE}/airlock"
    printf 'browser\n' > "${CORE}/proxy-target"
    touch "${CORE}/first-boot" "${CORE}/calls"
    cat > "${CORE}/metadata-utils.sh" <<'SH'
get_metadata_value() { echo prod; }
get_guest_attribute() { cat /home/core/status; }
set_metadata() {
    printf '%s %s\n' "$1" "$2" >> /home/core/calls
    if [[ "$1" == startup_script/status ]]; then printf '%s\n' "$2" > /home/core/status; fi
}
SH
    cat > "${CORE}/agent.env" <<'SH'
BACKEND=backend
PROXY=https://proxy.example
HOSTNAME=localhost
SHIM_PATH=/shim
REWRITE_WEBSOCKET_HOST=false
SH
    cat > "${CORE}/bin/docker" <<'SH'
#!/bin/bash
set -euo pipefail
echo "docker $*" >> /home/core/calls
case "$*" in
    'ps -aq --no-trunc --filter label=com.docker.compose.project=fixture --filter label=com.verily.workbench.proxy-target=true') cat /home/core/proxy-target ;;
    'inspect --format '*) echo fixture ;;
    'inspect application-server')
        jq -n --argjson airlock "$(cat /home/core/airlock)" '[{Config:{Labels:{
            "devcontainer.metadata":([{customizations:{workbench:{AIRLOCK_ENABLED:$airlock}}}] | tojson)
        }},NetworkSettings:{Ports:{"8080/tcp":[{HostIp:"0.0.0.0",HostPort:"8080"}]}}}]'
        ;;
    'start browser')
        test ! -f /home/core/fail-start
        touch /home/core/browser-running
        ;;
    'inspect browser')
        test -f /home/core/browser-running
        echo '[{"NetworkSettings":{"Ports":{"3000/tcp":[{"HostIp":"0.0.0.0","HostPort":"3000"}]}}}]'
        ;;
    'inspect application-server browser proxy-agent'|'inspect application-server application-server proxy-agent')
        echo '[{"State":{"Running":true}},{"State":{"Running":true}},{"State":{"Running":true}}]'
        ;;
    'image inspect workbench-local-snapshot:devcontainer') test -f /home/core/snapshot ;;
    'pull proxy-image'|'rm -f proxy-agent') exit 0 ;;
    'run '*) echo proxy-agent ;;
    *) echo "Unexpected Docker command: $*" >&2; exit 1 ;;
esac
SH
    chmod +x "${CORE}/bin/docker"
}

teardown() {
    docker run --rm --pull never --network none -v "${CORE}:/home/core" workbench-parser-test \
        chown -R "$(id -u):$(id -g)" /home/core
}

startup_script() {
    docker run --rm --pull never --network none \
        -v "${REPO_ROOT}:/repo:ro" -v "${CORE}:/home/core" \
        -e PATH=/home/core/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        workbench-parser-test bash "/repo/startupscript/butane/$1" "${@:2}"
}

assert_startup_rejected() {
    run startup_script 060-start-proxy-agent.sh proxy-image gcp
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"$1"* ]]
    printf 'STARTED\n' > "${CORE}/status"
    run startup_script probe-proxy-readiness.sh
    [ "${status}" -ne 0 ]
    [ "$(cat "${CORE}/status")" = ERROR ]
}

@test "proxy startup and readiness require completed setup and a snapshot" {
    touch "${CORE}/snapshot"
    assert_startup_rejected 'setup has not completed'

    touch "${CORE}/container-state.d/setup/post-create.done"
    rm "${CORE}/snapshot"
    assert_startup_rejected 'initial snapshot is unavailable'
    run grep -E '^docker (start|pull|rm|run) |^startup_script/status COMPLETE$' "${CORE}/calls"
    [ "${status}" = 1 ]

    touch "${CORE}/snapshot"
    touch "${CORE}/fail-start"
    run startup_script 060-start-proxy-agent.sh proxy-image gcp
    [ "${status}" -ne 0 ]
    [ ! -f "${CORE}/browser-running" ]
    run grep -E '^docker (pull|rm|run) ' "${CORE}/calls"
    [ "${status}" = 1 ]

    rm "${CORE}/fail-start"
    printf 'STARTED\n' > "${CORE}/status"
    startup_script 060-start-proxy-agent.sh proxy-image gcp
    startup_script probe-proxy-readiness.sh
    grep -q '^docker run ' "${CORE}/calls"
    [ "$(cat "${CORE}/status")" = COMPLETE ]
}

@test "ordinary apps can start the proxy and report ready without airlock state" {
    printf 'false\n' > "${CORE}/airlock"
    : > "${CORE}/proxy-target"
    startup_script 060-start-proxy-agent.sh proxy-image gcp
    startup_script probe-proxy-readiness.sh
    [ "$(cat "${CORE}/status")" = COMPLETE ]
    run grep -E '^docker start |^docker image inspect workbench-local-snapshot:devcontainer$' "${CORE}/calls"
    [ "${status}" = 1 ]
}
