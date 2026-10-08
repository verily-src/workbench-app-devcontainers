#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
    BUILD="$REPO_ROOT/startupscript/maintenance/build"
    FIXTURE="$BATS_TEST_DIRNAME/fixtures/maintenance-index"
    mkdir -p "$BATS_TEST_TMPDIR/gnupg"
}

@test "the image allowlist covers every existing bootstrap download on both clouds" {
    local file cloud source
    while read -r file; do
        for cloud in gcp aws; do
            source="${file//\$\{CLOUD\}/$cloud}"
            grep -Fxq "$source" "$BUILD/payload-files.txt"
            [ -f "$REPO_ROOT/startupscript/butane/$source" ]
        done
    done < <(awk '/^download / {gsub(/"/, "", $3); print $3}' "$REPO_ROOT/startupscript/butane/bootstrap-files.sh")
}

@test "image versions and source commits are validated before Docker starts" {
    run bash "$BUILD/build-image.sh" '../bad' "$BATS_TEST_TMPDIR/output"
    [ "$status" -ne 0 ]
    [[ "$output" == *'Invalid release version'* ]]
    run bash "$BUILD/build-image.sh" 1 "$BATS_TEST_TMPDIR/output" master
    [ "$status" -ne 0 ]
    [[ "$output" == *'Use a full source commit'* ]]
}

@test "public OpenPGP fixture verifies and rejects an altered index" {
    run gpgv --homedir "$BATS_TEST_TMPDIR/gnupg" --keyring "$FIXTURE/public.gpg" "$FIXTURE/SHA256SUMS.gpg" "$FIXTURE/SHA256SUMS"
    [ "$status" -eq 0 ]
    cp "$FIXTURE/SHA256SUMS" "$BATS_TEST_TMPDIR/SHA256SUMS"
    printf 'changed\n' >> "$BATS_TEST_TMPDIR/SHA256SUMS"
    run gpgv --homedir "$BATS_TEST_TMPDIR/gnupg" --keyring "$FIXTURE/public.gpg" "$FIXTURE/SHA256SUMS.gpg" "$BATS_TEST_TMPDIR/SHA256SUMS"
    [ "$status" -ne 0 ]
}

@test "maintenance records use the existing startup log stream on both clouds" {
    local cloud
    for cloud in gcp aws; do
        awk '/Tag vm.journal.startup/ {startup=1; next} /^\[INPUT\]/ {startup=0} startup {print}' \
            "$REPO_ROOT/startupscript/butane/$cloud/fluent-bit.conf" > "$BATS_TEST_TMPDIR/input"
        grep -q '_SYSTEMD_UNIT=workbench-update.service' "$BATS_TEST_TMPDIR/input"
        grep -q '_SYSTEMD_UNIT=workbench-maintenance.service' "$BATS_TEST_TMPDIR/input"
    done
}

@test "stats expose only version and action outcomes and tolerate missing state" {
    local state="$BATS_TEST_TMPDIR/state"
    mkdir "$state"
    run bash "$REPO_ROOT/startupscript/maintenance/status.sh" "$state"
    [ "$status" -eq 0 ]
    [ "$output" = null ]
    printf '%s\n' '{"active_version":"3","last_usable_version":"1"}' > "$state/boot.json"
    printf '%s\n' '{"actions":{"repair":{"status":"failed","last_error":"private action output"}}}' > "$state/state.json"
    run bash "$REPO_ROOT/startupscript/maintenance/status.sh" "$state"
    [ "$status" -eq 0 ]
    [ "$(jq -r .version <<< "$output")" = 3 ]
    [ "$(jq -r .actions.repair <<< "$output")" = failed ]
    [[ "$output" != *'private action output'* ]]
}
