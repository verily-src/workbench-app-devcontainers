#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    source "${REPO_ROOT}/startupscript/butane/container-utils.sh"
    APP_IDS=backend-id
    TARGET_IDS=frontend-id
    LOOKUP_EXIT=0
    PROJECT=our-project
    INSPECT_EXIT=0
    SNAPSHOT_INSPECT_EXIT=0
    export CONTAINER_STATE_FILE="${BATS_TEST_TMPDIR}/state"
    # Called by the sourced production helpers.
    # shellcheck disable=SC2317
    docker() {
        case "$*" in
            'ps -aq --no-trunc --filter name=^/application-server$')
                printf '%s\n' "${APP_IDS}"; return "${LOOKUP_EXIT}" ;;
            'ps -aq --no-trunc --filter label=com.docker.compose.project=our-project --filter label=com.verily.workbench.proxy-target=true')
                printf '%s\n' "${TARGET_IDS}"; return "${LOOKUP_EXIT}" ;;
            'inspect --format '*)
                [[ -n "${APP_IDS}" ]] || return 1
                printf '%s\n' "${PROJECT}"; return "${INSPECT_EXIT}" ;;
            'inspect '*) printf '%s\n' "${INSPECT}"; return "${INSPECT_EXIT}" ;;
            'image inspect workbench-local-snapshot:devcontainer') return "${SNAPSHOT_INSPECT_EXIT}" ;;
            *) echo "Unexpected Docker command: $*" >&2; return 1 ;;
        esac
    }
}

@test "snapshot validation rejects Docker errors and malformed metadata" {
    INSPECT='[]'
    INSPECT_EXIT=1 run validate_airlock_snapshot backend-id
    [ "${status}" -ne 0 ]
    INSPECT='[{"Config":{"Labels":{"devcontainer.metadata":"invalid-json"}}}]'
    run validate_airlock_snapshot backend-id
    [ "${status}" -ne 0 ]
}

@test "ordinary apps do not require airlock state, including an overridden image default" {
    SNAPSHOT_INSPECT_EXIT=1
    INSPECT='[{"Config":{"Labels":{}}}]'
    validate_airlock_snapshot backend-id
    INSPECT='[{"Config":{"Labels":{"devcontainer.metadata":"[{\"customizations\":{\"workbench\":{\"AIRLOCK_ENABLED\":true}}},{\"customizations\":{\"workbench\":{\"AIRLOCK_ENABLED\":false}}}]"}}}]'
    validate_airlock_snapshot backend-id
}

@test "proxy lookup prefers a project-scoped label and defaults to the app when absent" {
    [ "$(get_application_container)" = backend-id ]
    [ "$(find_proxy_container)" = frontend-id ]
    TARGET_IDS=''
    [ "$(find_proxy_container)" = application-server ]
}

@test "role lookup rejects ambiguity, missing apps, and Docker failures without falling back" {
    APP_IDS=''
    [ -z "$(get_application_container)" ]
    run find_proxy_container
    [ "${status}" -ne 0 ]
    APP_IDS=backend-id
    TARGET_IDS=$'one\ntwo'
    run find_proxy_container
    [ "${status}" -ne 0 ]
    PROJECT='' run find_proxy_container
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'has no Compose project label'* ]]
    TARGET_IDS='' LOOKUP_EXIT=1
    run find_proxy_container
    [ "${status}" -ne 0 ]
}

@test "readiness requires every role running and any declared health checks passing" {
    for state in '{"Running":false}' '{"Running":true,"Health":{"Status":"unhealthy"}}' \
        '{"Running":true,"Health":{"Status":"starting"}}'; do
        INSPECT="[{\"State\":${state}},{\"State\":{\"Running\":true}},{\"State\":{\"Running\":true}}]"
        run containers_ready backend-id frontend-id proxy-agent
        [ "${status}" -ne 0 ]
    done
    INSPECT='[{"State":{"Running":true,"Health":{"Status":"healthy"}}},{"State":{"Running":true}}]'
    containers_ready backend-id proxy-agent
    # Docker can return partial results and fail when another container is missing.
    set +o pipefail
    INSPECT_EXIT=1 run containers_ready backend-id frontend-id proxy-agent
    [ "${status}" -ne 0 ]
}
