#!/usr/bin/env bats
# Share-enabled VMs: detection from the VM's network tags, the proxy agent's
# --host, and the key registration retry. The production scripts run with
# /home/core rewritten into a per-test directory. The metadata server, WSM,
# Docker, openssl and sleep are stubbed on PATH.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    BUTANE="${REPO_ROOT}/startupscript/butane"
    export TEST_ROOT="${BATS_TEST_TMPDIR}/core"
    mkdir -p "${TEST_ROOT}/bin"
    touch "${TEST_ROOT}/sleeps" "${TEST_ROOT}/curl-calls"
    for script in 035-register-key.sh 060-start-proxy-agent.sh container-utils.sh service-utils.sh; do
        sed "s|/home/core|${TEST_ROOT}|g" "${BUTANE}/${script}" > "${TEST_ROOT}/${script}"
    done
    cp "${BUTANE}/gcp/metadata-utils.sh" "${TEST_ROOT}/metadata-utils.sh"
    export CONTAINER_STATE_FILE="${TEST_ROOT}/container-state"
    cat > "${TEST_ROOT}/agent.env" <<'SH'
BACKEND=backend
PROXY=https://proxy.example
HOSTNAME=localhost
SHIM_PATH=websocket-shim
REWRITE_WEBSOCKET_HOST=true
SH
    stub wb.sh 'echo fake-token' "${TEST_ROOT}"
    stub sleep 'echo "$1" >> "${TEST_ROOT}/sleeps"'
    stub openssl '
while (($#)); do [[ "$1" == -out ]] && out="$2"; shift; done
printf -- "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAfake\n-----END PUBLIC KEY-----\n" > "${out}"'
    # The metadata server and WSM. registerKey answers with the next status in
    # register-codes and repeats the last one.
    stub curl '
out="" fmt="" method=GET url=""
while (($#)); do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        -w) fmt="$2"; shift 2 ;;
        -X) method="$2"; shift 2 ;;
        -K) cat > /dev/null; shift 2 ;;
        -H|-d|--retry) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
echo "${method} ${url}" >> "${TEST_ROOT}/curl-calls"
respond() {
    if [[ -n "${out}" ]]; then printf "%s" "$2" > "${out}"; else printf "%s" "$2"; fi
    if [[ -n "${fmt}" ]]; then printf "%s" "$1"; fi
}
case "${url}" in
    */instance/tags) [[ -f "${TEST_ROOT}/tags" ]] || exit 22; cat "${TEST_ROOT}/tags" ;;
    */attributes/terra-cli-server) printf prod ;;
    */attributes/terra-workspace-id) printf ws-ufid ;;
    */attributes/wb-resource-id) printf resource-id ;;
    */attributes/*) exit 22 ;;
    */workspaceByUserFacingId/ws-ufid) respond 200 "{\"id\":\"ws-uuid\"}" ;;
    */gce-instances/resource-id) respond 200 "{\"attributes\":{\"signingAlgorithm\":\"UNSET\"}}" ;;
    */secrets/registerKey)
        code="$(head -n 1 "${TEST_ROOT}/register-codes")"
        if [[ "$(wc -l < "${TEST_ROOT}/register-codes")" -gt 1 ]]; then
            tail -n +2 "${TEST_ROOT}/register-codes" > "${TEST_ROOT}/codes.next"
            mv "${TEST_ROOT}/codes.next" "${TEST_ROOT}/register-codes"
        fi
        respond "${code}" "" ;;
    *) echo "Unexpected curl URL: ${url}" >&2; exit 99 ;;
esac'
    stub docker '
case "$*" in
    "inspect --format "*) echo fixture ;;
    "ps -aq --no-trunc --filter label=com.docker.compose.project=fixture --filter label=com.verily.workbench.proxy-target=true")
        cat "${TEST_ROOT}/proxy-target" 2>/dev/null || true ;;
    "inspect application-server"|"inspect frontend-id") cat "${TEST_ROOT}/inspect.json" ;;
    "start frontend-id") echo "start frontend-id" >> "${TEST_ROOT}/docker-start" ;;
    "pull proxy-image"|"rm -f proxy-agent") ;;
    "run "*) printf "%s\n" "$@" > "${TEST_ROOT}/docker-run" ;;
    *) echo "Unexpected Docker command: $*" >&2; exit 1 ;;
esac'
    export PATH="${TEST_ROOT}/bin:${PATH}"
    app_inspect 172.18.0.5
}

stub() {
    local dir="${3:-${TEST_ROOT}/bin}"
    printf '#!/bin/bash\nset -euo pipefail\n%s\n' "$2" > "${dir}/$1"
    chmod +x "${dir}/$1"
}

# Writes application-server's docker inspect output: an app on app-network at $1
# (none if empty), listening on 5000 and published on the host's 8080. Port 10000
# is exposed but not published, and sorts first.
app_inspect() {
    local networks='{"app-network":{"IPAddress":"'"$1"'"}}'
    [[ -n "$1" ]] || networks='{"bridge":{"IPAddress":"172.17.0.2"}}'
    cat > "${TEST_ROOT}/inspect.json" <<EOF
[{"Config":{"Labels":{"com.docker.compose.project":"fixture"}},
  "NetworkSettings":{
    "Ports":{"10000/tcp":null,"5000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8080"},{"HostIp":"::","HostPort":"8080"}]},
    "Networks":${networks}}}]
EOF
}

share_enabled() {
    echo '["http-server","share-enabled-app"]' > "${TEST_ROOT}/tags"
}

start_proxy_agent() {
    run bash "${TEST_ROOT}/060-start-proxy-agent.sh" proxy-image gcp
}

register_key() {
    printf '%s\n' "$@" > "${TEST_ROOT}/register-codes"
    run bash "${TEST_ROOT}/035-register-key.sh" gcp
}

register_calls() {
    grep -c '^POST .*/secrets/registerKey$' "${TEST_ROOT}/curl-calls"
}

@test "detection reads the share-enabled-app network tag and reports unreadable tags as unknown" {
    source "${TEST_ROOT}/metadata-utils.sh"
    share_enabled
    is_share_enabled_vm
    grep -q '^GET http://metadata.google.internal/computeMetadata/v1/instance/tags$' "${TEST_ROOT}/curl-calls"

    for tags in '[]' '["http-server"]' '["share-enabled-app-old"]'; do
        echo "${tags}" > "${TEST_ROOT}/tags"
        run is_share_enabled_vm
        [ "${status}" -eq 1 ]
        [ -z "${output}" ]
    done

    for tags in '<html>error</html>' '{"tags":["share-enabled-app"]}' ''; do
        printf '%s' "${tags}" > "${TEST_ROOT}/tags"
        run is_share_enabled_vm
        [ "${status}" -eq 2 ]
        [[ "${output}" == *"could not read the VM's network tags"* ]]
    done

    rm "${TEST_ROOT}/tags"
    run is_share_enabled_vm
    [ "${status}" -eq 2 ]
    [[ "${output}" == *"could not read the VM's network tags"* ]]
}

@test "EC2 instances are never share-enabled" {
    source "${BUTANE}/aws/metadata-utils.sh"
    run is_share_enabled_vm
    [ "${status}" -eq 1 ]
}

@test "only routable IPv4 addresses are accepted for the container" {
    source "${TEST_ROOT}/container-utils.sh"
    for ip in 172.18.0.5 10.0.0.1 192.168.1.254; do
        is_container_ipv4 "${ip}"
    done
    for ip in '' 127.0.0.1 127.1.2.3 0.0.0.0 169.254.169.254 169.254.0.1 256.1.1.1 \
        172.18.0 1.2.3.4.5 ::1 fe80::1 localhost ' 172.18.0.5'; do
        run is_container_ipv4 "${ip}"
        [ "${status}" -ne 0 ]
    done
}

@test "VMs that aren't share-enabled keep localhost and the published host port" {
    echo '["http-server"]' > "${TEST_ROOT}/tags"
    start_proxy_agent
    [ "${status}" -eq 0 ]
    grep -qx -- '--host=localhost:8080' "${TEST_ROOT}/docker-run"

    # A frontend is started and proxied as before.
    rm "${TEST_ROOT}/docker-run"
    echo frontend-id > "${TEST_ROOT}/proxy-target"
    start_proxy_agent
    [ "${status}" -eq 0 ]
    grep -qx 'start frontend-id' "${TEST_ROOT}/docker-start"
    grep -qx -- '--host=localhost:8080' "${TEST_ROOT}/docker-run"
}

@test "the agent isn't started while the VM's tags can't be read" {
    for tags in missing '<html>error</html>' ''; do
        if [[ "${tags}" == missing ]]; then
            rm -f "${TEST_ROOT}/tags"
        else
            printf '%s' "${tags}" > "${TEST_ROOT}/tags"
        fi
        start_proxy_agent
        [ "${status}" -ne 0 ]
        [[ "${output}" == *"could not tell whether this VM is share-enabled"* ]]
        [ ! -f "${TEST_ROOT}/docker-run" ]
    done
}

@test "share-enabled VMs refuse a separate frontend such as the virtual browser" {
    share_enabled
    echo frontend-id > "${TEST_ROOT}/proxy-target"
    start_proxy_agent
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"only apps served by application-server can be shared"* ]]
    [ ! -f "${TEST_ROOT}/docker-start" ]
    [ ! -f "${TEST_ROOT}/docker-run" ]
}

@test "share-enabled VMs dial the app's app-network address and container port" {
    share_enabled
    start_proxy_agent
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Share-enabled VM: the proxy agent forwards to 172.18.0.5:5000 on app-network"* ]]
    grep -qx -- '--host=172.18.0.5:5000' "${TEST_ROOT}/docker-run"
    grep -qx -- '--net=host' "${TEST_ROOT}/docker-run"
    run grep -- 'localhost' "${TEST_ROOT}/docker-run"
    [ "${status}" -eq 1 ]
}

@test "share-enabled VMs refuse to start the agent without a valid app-network address or port" {
    share_enabled
    for ip in 127.0.0.1 169.254.1.1 0.0.0.0 ''; do
        app_inspect "${ip}"
        start_proxy_agent
        [ "${status}" -ne 0 ]
        [[ "${output}" == *"not starting the proxy agent on this share-enabled VM"* ]]
        [ ! -f "${TEST_ROOT}/docker-run" ]
    done

    app_inspect 172.18.0.5
    jq '.[0].NetworkSettings.Ports = {"5000/tcp":null}' "${TEST_ROOT}/inspect.json" > "${TEST_ROOT}/unpublished.json"
    mv "${TEST_ROOT}/unpublished.json" "${TEST_ROOT}/inspect.json"
    start_proxy_agent
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"publishes no port"* ]]
    [ ! -f "${TEST_ROOT}/docker-run" ]
}

@test "share-enabled VMs retry a 403 key registration until it succeeds" {
    share_enabled
    register_key 403 403 204
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Key registration successful."* ]]
    [ "$(register_calls)" -eq 3 ]
    [ "$(cat "${TEST_ROOT}/sleeps")" = $'2\n4' ]
}

@test "share-enabled VMs stop retrying 403 after about 2 minutes" {
    share_enabled
    register_key 403
    [ "${status}" -eq 1 ]
    [[ "${output}" == *"Key registration failed with HTTP status 403."* ]]
    [ "$(register_calls)" -eq 8 ]
    [ "$(paste -sd ' ' "${TEST_ROOT}/sleeps")" = '2 4 8 16 30 30 30' ]
}

@test "other statuses and other VMs keep failing on the first refusal" {
    share_enabled
    for code in 400 401 404 409 500; do
        : > "${TEST_ROOT}/curl-calls"
        register_key "${code}" 204
        [ "${status}" -eq 1 ]
        [[ "${output}" == *"failed with HTTP status ${code}."* ]]
        [ "$(register_calls)" -eq 1 ]
    done

    for tags in '["http-server"]' '<html>error</html>'; do
        printf '%s' "${tags}" > "${TEST_ROOT}/tags"
        : > "${TEST_ROOT}/curl-calls"
        register_key 403 204
        [ "${status}" -eq 1 ]
        [ "$(register_calls)" -eq 1 ]
    done

    : > "${TEST_ROOT}/curl-calls"
    register_key 204
    [ "${status}" -eq 0 ]
    [ "$(register_calls)" -eq 1 ]
    [ ! -s "${TEST_ROOT}/sleeps" ]
}
