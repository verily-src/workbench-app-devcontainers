#!/usr/bin/env bats
# Requires Docker, cached python:3.12-alpine, and the installed Dev Container CLI.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../.." && pwd)"
    WRAPPER="$REPO_ROOT/startupscript/butane/devcontainer.sh"
    export TEST_DOCKER
    TEST_DOCKER=$(command -v docker)
    TEST_CLI="$REPO_ROOT/startupscript/butane/node_modules/.bin/devcontainer"
    export TEST_COMMITS="$BATS_TEST_TMPDIR/commits"
    export TEST_OFFLINE=false
    export BUILDX_CONFIG="$BATS_TEST_TMPDIR/buildx"
    export CONTAINER_STATE_FILE="$BATS_TEST_TMPDIR/container-state"
    export WORKBENCH_SETUP_STATE_DIR="$CONTAINER_STATE_FILE.d/setup"
    TEST_JUPYTER_HOME="$CONTAINER_STATE_FILE.d/jupyter-home"
    unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR
    PROJECT="airlock-$$-${BATS_TEST_NUMBER}-${RANDOM}"
    export TEST_BROWSER_NAME="$PROJECT-app-1"
    export TEST_BACKEND_SNAPSHOT="workbench-local-snapshot:$PROJECT-backend"
    FIXTURE="$BATS_TEST_TMPDIR/app"
    COMPOSE_FILE_PATH="$FIXTURE/docker-compose.yaml"
    TEST_BIN="$BATS_TEST_TMPDIR/bin"
    SEED_NAME="seed-$PROJECT"
    SEED_IMAGE="airlock-test:$PROJECT"
    BROWSER_IMAGE="airlock-test:$PROJECT-browser"
    mkdir -p "$FIXTURE" "$TEST_BIN"
    : > "$TEST_COMMITS"
    sed -n '/^handle_container_state_changed() {/,/^}/p' "$REPO_ROOT/startupscript/butane/050-parse-devcontainer.sh" > "$FIXTURE/hardware.sh"
    docker image inspect python:3.12-alpine >/dev/null
    cat > "$TEST_BIN/docker" <<'SH'
#!/bin/bash
set -euo pipefail
[[ "$1" != commit ]] || echo "$*" >> "$TEST_COMMITS"
if [[ "$TEST_OFFLINE" == true ]]; then
    case "$1" in
        pull|build|buildx) echo "Unexpected online operation: docker $1" >&2; exit 1 ;;
    esac
fi
# Keep the production names isolated to this test project.
args=()
for arg in "$@"; do
    case "$arg" in
        application-server) arg=$TEST_BROWSER_NAME ;;
        workbench-local-snapshot:devcontainer) arg=$TEST_BACKEND_SNAPSHOT ;;
    esac
    args+=("$arg")
done
exec "$TEST_DOCKER" "${args[@]}"
SH
    chmod +x "$TEST_BIN/docker"
    # macOS lacks flock; Linux CI and production use the real lock.
    if [[ "$(uname)" == Darwin ]]; then
        printf '#!/bin/sh\nexit 0\n' > "$TEST_BIN/flock"
        chmod +x "$TEST_BIN/flock"
    fi
}

teardown() {
    local image
    if [[ -f "$COMPOSE_FILE_PATH" ]]; then
        docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" down --volumes >/dev/null 2>&1 || true
    fi
    # Restore ownership of the test's host directory so Bats can remove it.
    if [[ -d "$TEST_JUPYTER_HOME" ]]; then
        docker run --rm --pull never -v "$TEST_JUPYTER_HOME:/home-data" python:3.12-alpine \
            chown -R "$(id -u):$(id -g)" /home-data >/dev/null 2>&1 || true
    fi
    docker rm -f -v "$SEED_NAME" >/dev/null 2>&1 || true
    if [[ -f "$FIXTURE/original.json" ]]; then
        image=$(jq -r '.[0].Config.Image' "$FIXTURE/original.json")
        # The CLI may build an image for the fixture; never remove the shared base.
        [[ "$image" != vsc-app-* ]] || docker image rm "$image" >/dev/null 2>&1 || true
    fi
    for image in "$SEED_IMAGE" "$BROWSER_IMAGE" "$TEST_BACKEND_SNAPSHOT"; do
        docker image rm "$image" >/dev/null 2>&1 || true
    done
}

lifecycle() {
    PATH="$TEST_BIN:$PATH" DEVCONTAINER_CLI="$TEST_CLI" "$WRAPPER" "$1" "$FIXTURE"
}

hardware_changed() {
    PATH="$TEST_BIN:$PATH" DEVCONTAINER_PATH="$FIXTURE" \
        bash -euo pipefail -c 'source "$1"; shift; handle_container_state_changed "$@"' bash "$FIXTURE/hardware.sh" "$@"
}

primary() { docker ps -aq --no-trunc --filter "label=devcontainer.local_folder=$FIXTURE"; }
snapshot_count() { wc -l < "$TEST_COMMITS" | tr -d ' '; }
edit_json() { jq "$2" "$1" > "$1.tmp" && mv "$1.tmp" "$1"; }
post_create() {
    local argument
    local -a hook=()
    while IFS= read -r argument; do hook+=("$argument"); done < <(jq -r '.postCreateCommand[]' "$FIXTURE/template.json")
    docker exec -w /workspace "$1" "${hook[@]}"
}

@test "CLI repeatedly restores the initial snapshot offline, preserving the browser and home" {
    local metadata original restored second browser_id browser_started initial_snapshot
    jq -n '[{
        postStartCommand:"test \"$FEATURE_SETTING\" = preserved && echo feature-start >> /startup-log",
        containerEnv:{FEATURE_SETTING:"preserved"}
    }]' > "$FIXTURE/metadata.json"
    metadata=$(jq -cr 'tojson | @json | gsub("\\$";"\\$")' "$FIXTURE/metadata.json")
    docker run -d --pull never --name "$SEED_NAME" python:3.12-alpine sleep infinity
    docker exec "$SEED_NAME" sh -c 'mkdir -p /home/jupyter; echo image-home > /home/jupyter/.seed; chown -R 1001:1001 /home/jupyter'
    # Supply an offline wheel that initial setup installs before the snapshot.
    docker exec -i "$SEED_NAME" python - <<'PY'
import zipfile
with zipfile.ZipFile('/tmp/preserved_pkg-1.0-py3-none-any.whl', 'w') as wheel:
    wheel.writestr('preserved_pkg.py', 'VALUE = 42\n')
    wheel.writestr('preserved_pkg-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: preserved-pkg\nVersion: 1.0\n')
    wheel.writestr('preserved_pkg-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
    wheel.writestr('preserved_pkg-1.0.dist-info/RECORD', '')
PY
    docker commit --change "LABEL devcontainer.metadata=$metadata" "$SEED_NAME" "$SEED_IMAGE"
    docker commit --change 'VOLUME ["/config"]' "$SEED_NAME" "$BROWSER_IMAGE"
    docker rm -f -v "$SEED_NAME"
    jq -n --arg project "$PROJECT" --arg image "$TEST_BACKEND_SNAPSHOT" --arg browser "$BROWSER_IMAGE" \
        --arg state "$WORKBENCH_SETUP_STATE_DIR" --arg home_dir "$TEST_JUPYTER_HOME" '{
        name:$project, services:{
            app:{image:$browser,pull_policy:"never",command:["sleep","infinity"],
                stop_grace_period:"1s",networks:["private"],shm_size:"64m"},
            backend:{image:$image,pull_policy:"never",command:["sleep","infinity"],
                stop_grace_period:"1s",networks:["private"],mem_limit:"128m",shm_size:"64m",
                volumes:["work:/data",".:/workspace","jupyter-home:/home/jupyter",($state + ":/var/lib/workbench/setup:ro")]}
        }, networks:{private:{internal:true}},volumes:{work:{},
            "jupyter-home":{driver:"local",driver_opts:{type:"none",o:"bind",device:$home_dir}}}
    }' > "$COMPOSE_FILE_PATH"
    jq -n --arg image "$SEED_IMAGE" \
        '{services:{backend:{image:$image}}}' > "$FIXTURE/docker-compose.build.yaml"
    cat > "$FIXTURE/.devcontainer.json" <<'JSON'
{"dockerComposeFile":["docker-compose.yaml","docker-compose.build.yaml"],"service":"backend","runServices":["app","backend"],
 "workspaceFolder":"/workspace","remoteUser":"root","userEnvProbe":"none",
 "postStartCommand":"echo user-start >> /startup-log",
 "customizations":{"workbench":{"AIRLOCK_ENABLED":true}}}
JSON
    node "$REPO_ROOT/startupscript/butane/jsoncStripComments.mjs" < "$REPO_ROOT/src/virtual-browser-jupyter/.devcontainer.json" > "$FIXTURE/template.json"
    jq --slurpfile template "$FIXTURE/template.json" --arg home_dir "$TEST_JUPYTER_HOME" '
        .postCreateCommand = $template[0].postCreateCommand |
        .initializeCommand = ($template[0].initializeCommand | map(
            if . == "/home/core/container-state.d/jupyter-home" then $home_dir else . end))' \
        "$FIXTURE/.devcontainer.json" > "$FIXTURE/.devcontainer.json.tmp"
    mv "$FIXTURE/.devcontainer.json.tmp" "$FIXTURE/.devcontainer.json"
    mkdir -p "$FIXTURE/startupscript"
    cat > "$FIXTURE/startupscript/post-startup.sh" <<'SH'
#!/bin/sh
set -eu
test ! -f /airlocked
python -m pip install --disable-pip-version-check --no-index /tmp/preserved_pkg-1.0-py3-none-any.whl
echo user-create >> /creation-log
SH
    chmod +x "$FIXTURE/startupscript/"*.sh
    hardware_changed 'gpu=1' 'shm-size=64m' 'mem-limit=128m'
    [ ! -d "$TEST_JUPYTER_HOME" ]
    lifecycle build
    [ ! -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done" ]
    lifecycle up
    [ -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done" ]
    original=$(primary)
    [ "$(snapshot_count)" = 1 ]
    initial_snapshot=$(docker image inspect -f '{{.Id}}' "$TEST_BACKEND_SNAPSHOT")
    browser_id=$(docker inspect -f '{{.Id}}' "$TEST_BROWSER_NAME")
    browser_started=$(docker inspect -f '{{.State.StartedAt}}' "$TEST_BROWSER_NAME")
    [ "$(cat "$TEST_JUPYTER_HOME/.seed")" = image-home ]
    docker exec --user 1001:1001 "$original" sh -c 'echo notebook > /home/jupyter/notebook.ipynb'
    [ "$(cat "$TEST_JUPYTER_HOME/notebook.ipynb")" = notebook ]
    docker inspect "$original" > "$FIXTURE/original.json"
    jq -e '.[0].Mounts | any(.Destination == "/var/lib/workbench/setup" and .RW == false)' "$FIXTURE/original.json"
    run docker exec --user root "$original" rm /var/lib/workbench/setup/post-create.done
    [ "$status" -ne 0 ]
    [[ "$output" == *'Read-only file system'* ]]
    run docker exec --user root "$original" sh -c 'echo changed > /var/lib/workbench/setup/post-create.done'
    [ "$status" -ne 0 ]
    [[ "$output" == *'Read-only file system'* ]]
    [ -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done" ]
    docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app sh -c 'echo browser-state > /browser-state; echo browser-settings > /config/preserved'
    docker exec "$original" sh -c 'touch /airlocked; echo named-volume > /data/preserved'

    export TEST_OFFLINE=true
    edit_json "$FIXTURE/.devcontainer.json" '.features = {"./must-not-be-reinstalled":{}}'
    edit_json "$COMPOSE_FILE_PATH" '
        .services.backend |= (.mem_limit = "256m" | .shm_size = "128m") |
        .services.app.shm_size = "128m"'
    edit_json "$FIXTURE/docker-compose.build.yaml" '
        .services.app.build = {context:".",dockerfile:"must-not-build"} |
        .services.backend.build = {context:".",dockerfile:"must-not-build"} |
        .services.builder = {build:"./must-not-build"}'
    cp "$COMPOSE_FILE_PATH" "$FIXTURE/expected-compose.yaml"
    lifecycle build
    hardware_changed 'gpu=1' 'shm-size=128m' 'mem-limit=256m'
    [ -z "$(primary)" ]
    [ "$(docker inspect -f '{{.Id}} {{.State.Running}}' "$TEST_BROWSER_NAME")" = "$browser_id true" ]
    lifecycle build
    lifecycle up
    restored=$(primary)
    [ "$restored" != "$original" ]
    [ "$(snapshot_count)" = 1 ]
    cmp "$COMPOSE_FILE_PATH" "$FIXTURE/expected-compose.yaml"
    [ "$(docker inspect -f '{{.Id}} {{.State.StartedAt}}' "$TEST_BROWSER_NAME")" = "$browser_id $browser_started" ]
    [ "$(docker inspect -f '{{.HostConfig.ShmSize}}' "$TEST_BROWSER_NAME")" = 67108864 ]
    [ "$(docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app cat /browser-state)" = browser-state ]
    [ "$(docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app cat /config/preserved)" = browser-settings ]
    docker inspect "$restored" | jq -e '.[0].HostConfig | .Memory == 268435456 and .ShmSize == 134217728'
    [ "$(docker exec "$restored" python -c 'import preserved_pkg; print(preserved_pkg.VALUE)')" = 42 ]
    [ "$(docker exec "$restored" cat /creation-log)" = user-create ]
    [ "$(docker exec "$restored" cat /data/preserved)" = named-volume ]
    [ "$(docker exec "$restored" cat /home/jupyter/notebook.ipynb)" = notebook ]
    # Home data lives on the host, outside the committed filesystem.
    docker run --rm --pull never --entrypoint sh "$TEST_BACKEND_SNAPSHOT" -c 'test ! -f /home/jupyter/notebook.ipynb'
    [ "$(docker exec "$restored" cat /startup-log)" = $'feature-start\nuser-start\nfeature-start\nuser-start' ]

    # A normal restart keeps the container and runs startup hooks without snapshotting.
    docker stop "$restored"
    lifecycle build
    lifecycle up
    [ "$(primary)" = "$restored" ]
    [ "$(snapshot_count)" = 1 ]
    [ "$(docker exec "$restored" cat /creation-log)" = user-create ]
    [ "$(docker exec "$restored" sh -c 'wc -l < /startup-log')" = 6 ]

    # Another recreation reuses the initial image, discarding later writable-layer changes.
    docker exec "$restored" sh -c 'echo installed-later > /late-user-install'
    docker exec --user 1001:1001 "$restored" sh -c 'echo edited-notebook > /home/jupyter/notebook.ipynb'
    docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app sh -c 'echo updated-browser-state > /browser-state'
    edit_json "$COMPOSE_FILE_PATH" '.services.backend.mem_limit = "192m"'
    hardware_changed 'gpu=1' 'shm-size=128m' 'mem-limit=192m'
    lifecycle build
    lifecycle up
    second=$(primary)
    [ "$second" != "$restored" ]
    [ "$(snapshot_count)" = 1 ]
    [ "$(docker image inspect -f '{{.Id}}' "$TEST_BACKEND_SNAPSHOT")" = "$initial_snapshot" ]
    docker inspect "$second" | jq -e '.[0].HostConfig.Memory == 201326592'
    docker exec "$second" test ! -f /late-user-install
    [ "$(docker exec "$second" python -c 'import preserved_pkg; print(preserved_pkg.VALUE)')" = 42 ]
    [ "$(docker exec "$second" cat /creation-log)" = user-create ]
    [ "$(docker exec "$second" sh -c 'wc -l < /startup-log')" = 4 ]
    [ "$(docker exec "$second" cat /home/jupyter/notebook.ipynb)" = edited-notebook ]
    [ "$(docker inspect -f '{{.Id}} {{.State.StartedAt}}' "$TEST_BROWSER_NAME")" = "$browser_id $browser_started" ]
    [ "$(docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app cat /browser-state)" = updated-browser-state ]
    [ "$(docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE_PATH" exec -T app cat /config/preserved)" = browser-settings ]
}

@test "virtual-browser post-create guards only read the host completion marker" {
    local template
    mkdir -p "$FIXTURE/startupscript"
    cat > "$FIXTURE/startupscript/post-startup.sh" <<'SH'
#!/bin/sh
set -eu
echo attempt >> /workspace/attempts
test ! -f /workspace/fail-setup
printf '%s\n' "$@" > /workspace/arguments
SH
    chmod +x "$FIXTURE/startupscript/post-startup.sh"
    mkdir -p "$WORKBENCH_SETUP_STATE_DIR"
    docker run -d --pull never --name "$SEED_NAME" -v "$FIXTURE:/workspace" \
        -v "$WORKBENCH_SETUP_STATE_DIR:/var/lib/workbench/setup:ro" python:3.12-alpine sleep infinity
    for template in virtual-browser-jupyter virtual-browser-rstudio; do
        node "$REPO_ROOT/startupscript/butane/jsoncStripComments.mjs" < "$REPO_ROOT/src/$template/.devcontainer.json" > "$FIXTURE/template.json"
        rm -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done"
        : > "$FIXTURE/attempts"
        touch "$FIXTURE/fail-setup"
        run post_create "$SEED_NAME"
        [ "$status" -ne 0 ]
        [ ! -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done" ]
        rm "$FIXTURE/fail-setup"
        post_create "$SEED_NAME"
        [ ! -f "$WORKBENCH_SETUP_STATE_DIR/post-create.done" ]
        [ "$(cat "$FIXTURE/arguments")" = "$(jq -r '.postCreateCommand[4:][]' "$FIXTURE/template.json")" ]
        touch "$WORKBENCH_SETUP_STATE_DIR/post-create.done"
        docker exec "$SEED_NAME" test -f /var/lib/workbench/setup/post-create.done
        touch "$FIXTURE/fail-setup"
        post_create "$SEED_NAME"
        [ "$(cat "$FIXTURE/attempts")" = $'attempt\nattempt' ]
    done
}

@test "standard recreation uses the CLI and runs creation hooks for the new container" {
    local original replacement
    jq -n --arg project "$PROJECT" '{name:$project,services:{
        backend:{image:"python:3.12-alpine",pull_policy:"never",command:["sleep","infinity"],stop_grace_period:"1s",
            mem_limit:"128m",shm_size:"64m",networks:["private"],volumes:["work:/data"]}
    },networks:{private:{internal:true}},volumes:{work:{}}}' > "$COMPOSE_FILE_PATH"
    cat > "$FIXTURE/.devcontainer.json" <<'JSON'
{"dockerComposeFile":"docker-compose.yaml","service":"backend","workspaceFolder":"/tmp","remoteUser":"root","userEnvProbe":"none",
 "postCreateCommand":"echo created >> /data/creation-log","postStartCommand":"echo started >> /data/startup-log"}
JSON
    lifecycle build
    lifecycle up
    original=$(primary)
    docker inspect "$original" > "$FIXTURE/original.json"
    docker exec "$original" sh -c 'echo user-data > /data/preserved'
    [ "$(docker exec "$original" cat /data/creation-log)" = created ]
    docker stop "$original"
    lifecycle build
    lifecycle up
    [ "$(primary)" = "$original" ]
    [ "$(docker exec "$original" cat /data/creation-log)" = created ]
    [ "$(docker exec "$original" cat /data/startup-log)" = $'started\nstarted' ]

    edit_json "$COMPOSE_FILE_PATH" '.services.backend |= (.mem_limit = "192m" | .shm_size = "128m")'
    docker rm -f "$original"
    lifecycle build
    lifecycle up
    replacement=$(primary)
    [ "$replacement" != "$original" ]
    docker inspect "$replacement" | jq -e '.[0].HostConfig | .Memory == 201326592 and .ShmSize == 134217728'
    [ "$(docker exec "$replacement" cat /data/preserved)" = user-data ]
    [ "$(docker exec "$replacement" cat /data/creation-log)" = $'created\ncreated' ]
    [ "$(docker exec "$replacement" cat /data/startup-log)" = $'started\nstarted\nstarted' ]
    [ "$(snapshot_count)" = 0 ]
}
