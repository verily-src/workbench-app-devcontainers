#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    export OUTPUT_DIR="${BATS_TEST_TMPDIR}/report" PORT=8080
    mkdir -p "${OUTPUT_DIR}"
    printf '["application-server","playground","db"]\n' > "${OUTPUT_DIR}/expected-containers.json"
    sed -n '/^playground_work() {/,/^expected_services() {/p' "${REPO_ROOT}/tests/common/workload.sh" | sed '$d' > "${BATS_TEST_TMPDIR}/functions.sh"
    source "${BATS_TEST_TMPDIR}/functions.sh"
}

docker() {
    [[ "$*" == "inspect --format {{.Config.Image}} application-server" ]] || return 1
    echo caddy:2.11-alpine
}

curl() {
    local url
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -d) printf '%s\n' "$2" > "${OUTPUT_DIR}/request.json"; shift 2 ;;
            *) url="$1"; shift ;;
        esac
    done
    case "${url}" in
        */_app) printf '{"id":42}\n' ;;
        */_app/42) printf '{"status":"%s"}\n' "${PLAYGROUND_STATUS:-active}" ;;
        */_app/logs\?tail=100) printf '{"logs":"fixture build failed: missing base image"}\n' ;;
        */dependency-fixture/)
            jq -e '.caddy_config | contains("uri strip_prefix /{{.AppName}}") and contains("reverse_proxy {{.ContainerName}}:{{.Port}}")' "${OUTPUT_DIR}/request.json" >/dev/null || return 22
            echo dependency-workload-ok ;;
        *) return 1 ;;
    esac
}

@test "Playground fixture builds from the local named image and registers its routed child" {
    playground_work
    jq -e '.dockerfile | startswith("FROM caddy:2.11-alpine\n") and contains("ENTRYPOINT [\"caddy\"]\nCMD [\"file-server\"")' "${OUTPUT_DIR}/request.json"
    jq -e '.caddy_config | startswith("@{{.AppName}} path /{{.AppName}} /{{.AppName}}/*")' "${OUTPUT_DIR}/request.json"
    jq -e 'index("app-42") != null' "${OUTPUT_DIR}/expected-containers.json"
}

@test "Playground build failures keep diagnostics and never count the child as running" {
    export PLAYGROUND_STATUS=failed
    run playground_work
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'fixture build failed: missing base image'* ]]
    jq -e 'index("app-42") == null' "${OUTPUT_DIR}/expected-containers.json"
}
