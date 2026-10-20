#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../../.." && pwd)"
    ROOT="$BATS_TEST_TMPDIR"
    IMAGE="maintenance-wb-fixture:$(basename "$ROOT" | tr '[:upper:]' '[:lower:]')"
    mkdir -p "$ROOT/core/wb" "$ROOT/extension"
    printf 'FROM scratch\nLABEL php184302="fixture"\n' > "$ROOT/extension/Dockerfile"
    ln -s "$ROOT/extension/Dockerfile" "$ROOT/core/wb/Dockerfile"
    cat > "$ROOT/core/wb/values.sh" <<EOF
WB_ROOT="$ROOT/core/wb"
WB_DOCKERFILE="$ROOT/core/wb/Dockerfile"
WB_IMAGE_NAME="$IMAGE"
WB_CONTEXT_DIR="$ROOT/core/wb/context"
WB_LOGIN_MODE=fixture
EOF
    cat > "$ROOT/core/metadata-utils.sh" <<'EOF'
get_metadata_value() { printf fixture; }
EOF
    cat > "$ROOT/core/wb.sh" <<'EOF'
#!/bin/bash
case "$*" in
    'server status') echo 'Current server: fixture' ;;
    'auth status --format json') echo '{"loggedIn":true}' ;;
    'workspace describe --format json') echo '{"id":"fixture"}' ;;
    *) exit 99 ;;
esac
EOF
    chmod +x "$ROOT/core/wb.sh"
    sed "s#/home/core#$ROOT/core#g" "$REPO_ROOT/startupscript/butane/030-configure-wb.sh" > "$ROOT/configure-wb.sh"
}

teardown() {
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
}

@test "fresh wb build resolves the extension Dockerfile outside its context" {
    run bash "$ROOT/configure-wb.sh"
    [ "$status" -eq 0 ]
    [ "$(docker image inspect --format '{{index .Config.Labels "php184302"}}' "$IMAGE")" = fixture ]
    local before
    before="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
    run bash "$ROOT/configure-wb.sh"
    [ "$status" -eq 0 ]
    [ "$(docker image inspect --format '{{.Id}}' "$IMAGE")" = "$before" ]
}
