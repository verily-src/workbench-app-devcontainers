#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly core="${WORKBENCH_ROOT:-}/home/core"
readonly folder="${core}/devcontainer/${APP_DEVCONTAINER_PATH:-}"
readonly mode="${WORKBENCH_MODE:?WORKBENCH_MODE is required}"
readonly cloud="${WORKBENCH_CLOUD:?WORKBENCH_CLOUD is required}"
[[ "${mode}" == runtime || "${mode}" == cache ]]
[[ "${cloud}" == gcp || "${cloud}" == aws ]]

case "${1:?Usage: app-host.sh startup|failure|logging|os-update}" in
    startup)
        "${core}/pre-devcontainer.sh"
        # shellcheck source=/dev/null
        source "${core}/metadata-utils.sh"
        set_metadata startup_script/status STARTED
        /bin/bash "${core}/install-node.sh"
        /bin/bash "${core}/create-docker-network.sh"
        if [[ "${mode}" == runtime ]]; then
            /bin/bash "${core}/configure-wb.sh"
            /bin/bash "${core}/register-key.sh" "${cloud}"
        fi
        if [[ "${cloud}" == gcp ]]; then
            /bin/bash "${core}/docker-auth.sh" "${APP_DEVCONTAINER_PATH}" "${APP_ARTIFACT_REGISTRY_LOCATIONS}"
        else
            /bin/bash "${core}/docker-auth.sh"
        fi
        args=("${APP_GIT_URL}")
        [[ -z "${APP_GIT_BRANCH:-}" ]] || args+=("${APP_GIT_BRANCH}")
        /bin/bash "${core}/git-clone-devcontainer.sh" "${args[@]}"
        /bin/bash "${core}/parse-devcontainer.sh" "${folder}" "${cloud}" true "${APP_CONTAINER_IMAGE}" "${APP_PORT}"
        /bin/bash "${core}/docker-auth-secrets.sh"
        /bin/bash "${core}/devcontainer.sh" build "${folder}"
        if [[ "${mode}" == cache ]]; then
            exec /bin/bash "${core}/prepare-devcontainer-cache.sh" -d "${folder}" "${APP_PROXY_IMAGE}"
        fi
        /bin/bash "${core}/devcontainer.sh" up "${folder}" || true
        /bin/bash "${core}/provide-secrets.sh" "${cloud}"
        exec /bin/bash "${core}/start-proxy-agent.sh" "${APP_PROXY_IMAGE}" "${APP_COMPUTE_ENGINE}"
        ;;
    failure)
        shutdown=false
        [[ "${mode}" != cache ]] || shutdown=true
        exec /bin/bash "${core}/devcontainer-failure-handler.sh" "${shutdown}"
        ;;
    logging) exec /bin/bash "${core}/run-fluent-bit.sh" "${cloud}" ;;
    os-update) exec /bin/bash "${core}/update-flatcar.sh" "${APP_FLATCAR_VERSION_URL}" ;;
    *) echo 'Unknown host startup operation' >&2; exit 2 ;;
esac
