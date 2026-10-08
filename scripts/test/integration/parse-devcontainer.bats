#!/usr/bin/env bats
# Run the complete Linux startup parser, with cloud metadata and Docker mocked.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../.." && pwd)"
    CORE="$BATS_TEST_TMPDIR/core"
    mkdir -p "$CORE/bin" "$CORE/app"
    printf 'MemTotal: 8388608 kB\n' > "$CORE/meminfo"
    printf '64m\n' > "$CORE/shm-size"
    : > "$CORE/calls"
    : > "$CORE/container-id"
    docker image inspect workbench-parser-test >/dev/null

    cat > "$CORE/bin/docker" <<'SH'
#!/bin/bash
set -euo pipefail
echo "docker $*" >> /home/core/calls
case "$*" in
    'image inspect workbench-local-snapshot:devcontainer') test -f /home/core/snapshot ;;
    'ps -aq --no-trunc --filter name=^/application-server$') cat /home/core/container-id ;;
    'rm -f primary-id') : > /home/core/container-id ;;
    'update --memory '*' primary-id') : ;;
    *) echo "Unexpected Docker command: $*" >&2; exit 1 ;;
esac
SH
    cat > "$CORE/bin/awk" <<'SH'
#!/bin/bash
# Control host RAM while keeping the production calculation intact.
args=("$@")
for i in "${!args[@]}"; do
    [[ "${args[$i]}" != /proc/meminfo ]] || args[$i]=/home/core/meminfo
done
exec /usr/bin/awk "${args[@]}"
SH
    cat > "$CORE/bin/nvidia-smi" <<'SH'
#!/bin/sh
test -f /home/core/gpu
SH
    cat > "$CORE/prefetch-oci-features.sh" <<'SH'
#!/bin/sh
echo prefetch >> /home/core/calls
# A failed prefetch on first boot must still allow the CLI to fetch features.
exit 1
SH
    cat > "$CORE/metadata-utils.sh" <<'SH'
get_metadata_value() { cat /home/core/shm-size; }
get_guest_attribute() { cat /home/core/guest-shm-size; }
set_metadata() { printf '%s\n' "$2" > /home/core/published.json; }
SH
    chmod +x "$CORE/bin/"* "$CORE/prefetch-oci-features.sh"
}

teardown() {
    # Linux Docker writes as root; let Bats remove only this test's fixture.
    docker run --rm --pull never --network none -v "$CORE:/home/core" workbench-parser-test \
        chown -R "$(id -u):$(id -g)" /home/core
}

parse() {
    docker run --rm --pull never --network none \
        -v "$REPO_ROOT:/repo:ro" -v "$CORE:/home/core" \
        -e PATH=/home/core/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
        workbench-parser-test bash -ec '
            ln -sfn /repo /home/core/devcontainer
            ln -sfn /repo/startupscript/butane/jsoncStripComments.mjs /home/core/jsoncStripComments.mjs
            exec bash /repo/startupscript/butane/050-parse-devcontainer.sh "$1" gcp true
        ' bash "${1:-/home/core/app}"
}

render() {
    docker compose -f "$CORE/app/docker-compose.yaml" config --format json > "$CORE/rendered.json"
}

assert_no_call() {
    run grep -E "$1" "$CORE/calls"
    [ "$status" = 1 ]
}

check_settings() {
    local gpu=$1 shm=$2 memory=$3
    render
    jq -e --argjson gpu "$gpu" --argjson shm "$shm" --argjson memory "$memory" '
        .services.app |
        (.shm_size | tonumber) == $shm and (.mem_limit // 0 | tonumber) == $memory and
        ((.deploy.resources.reservations.devices // [] | length) == $gpu)
    ' "$CORE/rendered.json"
    if [[ "$AIRLOCKED" == true ]]; then
        jq -S '.services.browser' "$CORE/rendered.json" > "$CORE/browser.json"
        cmp "$CORE/browser.json" "$CORE/initial-browser.json"
    fi
}

check_airlocked_config() {
    local template=$1 expected_port=$2 file
    local -a compose=(docker compose --project-directory "$REPO_ROOT/src/$template" -f "$CORE/app/docker-compose.yaml")
    node "$REPO_ROOT/startupscript/butane/jsoncStripComments.mjs" < "$CORE/app/.devcontainer.json" > "$CORE/config.json"
    jq -e '.runServices == ["browser", .service] and .remoteUser == "root"' "$CORE/config.json"
    jq -e --arg template "$template" --slurpfile config "$CORE/config.json" '
        (.services | keys) == ["app", "browser"] and
        .services.browser.image == "workbench-virtual-browser:app" and
        .services.browser.labels["com.verily.workbench.proxy-target"] == "true" and
        .services.app.container_name == "application-server" and
        .services.app.image == "workbench-local-snapshot:devcontainer" and
        all(.services[]; .pull_policy == "never" and (has("build") | not)) and
        any(.services.app.volumes[]; .target == "/var/lib/workbench/setup" and .read_only == true) and
        (if $template == "virtual-browser-jupyter" then
            any(.services.app.volumes[]; .target == "/home/jupyter" and .source == "jupyter-home") and
            ((.volumes["jupyter-home"].driver_opts // {}) | length == 0) and
            ($config[0] | has("initializeCommand") | not)
         else true end)
    ' "$CORE/rendered.json"

    while IFS= read -r file; do
        compose+=(-f "$REPO_ROOT/src/$template/$file")
    done < <(jq -r '.dockerComposeFile[] | select(. != "docker-compose.yaml")' "$CORE/config.json")
    "${compose[@]}" config --format json --no-path-resolution > "$CORE/build.json"
    jq -e --arg template "$template" --arg expected_port "$expected_port" '
        (.services.browser.build.context | endswith("/browser-common")) and
        .services.browser.environment.CHROME_CLI == ("--kiosk http://" + .services.browser.build.args.APP_ORIGIN) and
        .services.browser.build.args.APP_ORIGIN == (.services.app.container_name + ":" + $expected_port) and
        (if $template == "virtual-browser-jupyter" then
            .services.app.image == "workbench-virtual-browser:jupyterlab" and
            .services.app.build.additional_contexts["jupyter-extension-builder"] == "service:jupyter-common-extension-builder"
         else
            (.services.app.image | startswith("ghcr.io/rocker-org/devcontainer/tidyverse@sha256:")) and
            .services.app.pull_policy == "missing"
         end)
    ' "$CORE/build.json"
}

exercise_lifecycle() {
    local template=$1 expected_port=${3:-}
    AIRLOCKED=$2
    cp "$REPO_ROOT/src/$template/.devcontainer.json" "$CORE/app/.devcontainer.json"
    cp "$REPO_ROOT/src/$template/docker-compose.yaml" "$CORE/app/docker-compose.yaml"

    # Initial creation: render from the actual template, no existing container.
    parse
    [ "$(cat "$CORE/container-state")" = $'gpu=1\nshm-size=64m\nmem-limit=7168m' ]
    [ "$(grep -c '^prefetch$' "$CORE/calls")" = 1 ]
    assert_no_call '^docker rm '
    render
    jq -S '.services.browser' "$CORE/rendered.json" > "$CORE/initial-browser.json"
    check_settings 0 67108864 7516192768
    [ -f "$CORE/app/startupscript/post-startup.sh" ]
    [ -f "$CORE/app/.devcontainer/features/workbench-tools/devcontainer-feature.json" ]
    if [[ "$AIRLOCKED" == true ]]; then
        check_airlocked_config "$template" "$expected_port"
    fi

    printf 'primary-id\n' > "$CORE/container-id"
    # A local snapshot must only suppress prefetch for an airlocked app.
    touch "$CORE/snapshot"
    if [[ "$AIRLOCKED" == true ]]; then
        # The wrapper writes a minimal config when restoring; the parser must
        # recover the complete original config from its saved template.
        printf '{"service":"app"}\n' > "$CORE/app/.devcontainer.json"
    fi
    : > "$CORE/calls"
    parse
    [ "$(cat "$CORE/container-id")" = primary-id ]
    assert_no_call '^docker (ps|rm) '
    if [[ "$AIRLOCKED" == true ]]; then
        assert_no_call '^prefetch$'
        jq -e '.AIRLOCK_ENABLED == true' "$CORE/published.json"
    else
        [ "$(cat "$CORE/calls")" = prefetch ]
    fi
    check_settings 0 67108864 7516192768

    # Each resource changes independently; a trailing slash still addresses
    # the same app configuration and fixed primary container.
    printf 'MemTotal: 4194304 kB\n' > "$CORE/meminfo"
    : > "$CORE/calls"
    parse /home/core/app/
    # Memory changes keep the container and its writable layer.
    grep -qx 'docker update --memory 3072m --memory-swap 6144m primary-id' "$CORE/calls"
    assert_no_call '^docker rm '
    [ "$(cat "$CORE/container-id")" = primary-id ]
    check_settings 0 67108864 3221225472

    printf '128m\n' > "$CORE/shm-size"
    : > "$CORE/calls"
    parse
    grep -qx 'docker rm -f primary-id' "$CORE/calls"
    check_settings 0 134217728 3221225472

    printf 'primary-id\n' > "$CORE/container-id"
    touch "$CORE/gpu"
    : > "$CORE/calls"
    parse
    grep -qx 'docker rm -f primary-id' "$CORE/calls"
    check_settings 1 134217728 3221225472
    # Re-rendering must not accumulate GPU reservation blocks.
    printf 'primary-id\n' > "$CORE/container-id"
    : > "$CORE/calls"
    parse
    assert_no_call '^docker rm '
    check_settings 1 134217728 3221225472

    # Removing the GPU, invalid shm metadata and too little RAM restore defaults.
    rm "$CORE/gpu"
    printf 'invalid\n' > "$CORE/shm-size"
    printf 'MemTotal: 1048576 kB\n' > "$CORE/meminfo"
    : > "$CORE/calls"
    parse
    [ "$(grep -c '^docker rm -f primary-id$' "$CORE/calls")" = 1 ]
    [ "$(cat "$CORE/container-state")" = $'gpu=1\nshm-size=64m\nmem-limit=' ]
    check_settings 0 67108864 0

    # Empty instance metadata falls back to the stored guest setting.
    : > "$CORE/shm-size"
    printf '256m\n' > "$CORE/guest-shm-size"
    parse
    check_settings 0 268435456 0
}

@test "complete parser handles Jupyter first creation and airlocked restarts" {
    exercise_lifecycle virtual-browser-jupyter true 8888
}

@test "complete parser handles RStudio first creation and airlocked restarts" {
    exercise_lifecycle virtual-browser-rstudio true 8787
}

@test "complete parser handles regular app first creation and restarts" {
    exercise_lifecycle r-analysis false
}
