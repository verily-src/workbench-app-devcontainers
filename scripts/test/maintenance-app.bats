#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    WRAPPER="${REPO_ROOT}/startupscript/maintenance/app-host.sh"
    export WORKBENCH_ROOT="${BATS_TEST_TMPDIR}/root"
    export WORKBENCH_CLOUD=gcp WORKBENCH_MODE=runtime
    export APP_GIT_URL='https://example.invalid/a repo'
    export APP_GIT_BRANCH='branch with spaces'
    export APP_DEVCONTAINER_PATH='src/a folder'
    export APP_CONTAINER_IMAGE=example.invalid/app:1 APP_PORT=8080
    export APP_ARTIFACT_REGISTRY_LOCATIONS=us-central1,us-east1
    export APP_PROXY_IMAGE=example.invalid/proxy:1 APP_COMPUTE_ENGINE=GCP
    export CALLS="${BATS_TEST_TMPDIR}/calls"
    local core="${WORKBENCH_ROOT}/home/core" name
    mkdir -p "${core}"
    for name in pre-devcontainer install-node create-docker-network configure-wb register-key \
        docker-auth git-clone-devcontainer parse-devcontainer docker-auth-secrets devcontainer \
        prepare-devcontainer-cache provide-secrets start-proxy-agent devcontainer-failure-handler; do
        cat > "${core}/${name}.sh" <<'SH'
#!/bin/bash
name=${0##*/}
jq -cn --arg script "${name}" --args '{script:$script,args:$ARGS.positional}' -- "$@" >> "${CALLS}"
[[ "${FAIL_SCRIPT:-}" != "${name}" ]] || exit 1
[[ "${FAIL_UP:-false}" != true || "$1" != up ]] || exit 1
SH
        chmod +x "${core}/${name}.sh"
    done
    cat > "${core}/metadata-utils.sh" <<'SH'
set_metadata() {
    jq -cn --arg script metadata --args '{script:$script,args:$ARGS.positional}' -- "$@" >> "${CALLS}"
}
SH
}

@test "runtime startup preserves quoted arguments and existing build/up contract" {
    "${WRAPPER}" startup
    jq -se 'map(select(.script == "git-clone-devcontainer.sh"))[0].args == ["https://example.invalid/a repo", "branch with spaces"]' "${CALLS}"
    jq -se 'map(select(.script == "devcontainer.sh") | .args[0]) == ["build", "up"]' "${CALLS}"
    jq -se 'map(.script) | index("configure-wb.sh") < index("register-key.sh") and index("provide-secrets.sh") < index("start-proxy-agent.sh")' "${CALLS}"
}

@test "cache mode skips runtime registration and shuts down through the existing cache script" {
    WORKBENCH_MODE=cache WORKBENCH_CLOUD=aws APP_GIT_BRANCH='' "${WRAPPER}" startup
    jq -se 'map(.script) | (index("configure-wb.sh") == null) and (index("provide-secrets.sh") == null) and .[-1] == "prepare-devcontainer-cache.sh"' "${CALLS}"
    jq -se 'map(select(.script == "docker-auth.sh"))[0].args == []' "${CALLS}"
    jq -se 'map(select(.script == "git-clone-devcontainer.sh"))[0].args == ["https://example.invalid/a repo"]' "${CALLS}"
}

@test "required setup failures stop startup while up failures retain later validation" {
    FAIL_SCRIPT=register-key.sh run "${WRAPPER}" startup
    [ "${status}" -ne 0 ]
    jq -se 'map(.script) | index("devcontainer.sh") == null' "${CALLS}"
    : > "${CALLS}"
    FAIL_UP=true "${WRAPPER}" startup
    jq -se '.[-1].script == "start-proxy-agent.sh"' "${CALLS}"
}

@test "app failures request shutdown only in cache mode" {
    "${WRAPPER}" failure
    WORKBENCH_MODE=cache "${WRAPPER}" failure
    jq -se 'map(.args) == [["false"],["true"]]' "${CALLS}"
}
