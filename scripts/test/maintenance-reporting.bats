#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    REPORTER="$REPO_ROOT/startupscript/maintenance/report-failure.sh"
    STATE_DIR="$BATS_TEST_TMPDIR/state"
    export TEST_ROOT="$BATS_TEST_TMPDIR"
    export SERVICE_RESULT=exit-code
    mkdir -p "$TEST_ROOT/bin" "$STATE_DIR"
    printf '%s\n' '{"active_version":"202610080003"}' > "$STATE_DIR/boot.json"
    printf '%s\n' '{"schema":1,"actions":{"repair":{"status":"failed","last_error":"PRIVATE_ACTION_OUTPUT"}}}' > "$STATE_DIR/state.json"
    : > "$TEST_ROOT/calls"
    cat > "$TEST_ROOT/bin/curl" <<'SCRIPT'
#!/bin/bash
printf '%s\n' "$*" >> "$TEST_ROOT/calls"
[[ "$*" != *FAKEMetadataToken* && "$*" != *FAKESecret* && "$*" != *FAKESession* ]] || exit 99
[[ "$*" == *'--connect-timeout '* && "$*" == *'--max-time '* ]] || exit 99
url="${!#}"
[[ "${CURL_FAILURE:-}" != all ]] || exit 28
case "$url" in
    */guest-attributes/startup_script/message)
        [[ "${CURL_FAILURE:-}" != message ]] || exit 22 ;;
    */guest-attributes/startup_script/status) ;;
    */latest/api/token)
        if [[ "${MALFORMED:-}" == token ]]; then printf 'bad\ntoken'; else printf FAKEMetadataToken; fi ;;
    */latest/dynamic/instance-identity/document)
        cat > "$TEST_ROOT/token-config"
        if [[ "${MALFORMED:-}" == document ]]; then printf '{}';
        else printf '%s' '{"region":"us-east-1","instanceId":"i-0123456789abcdef0"}'; fi ;;
    */latest/meta-data/iam/security-credentials/)
        cat > "$TEST_ROOT/token-config"
        if [[ "${MALFORMED:-}" == role ]]; then printf '../bad'; else printf TestRole; fi ;;
    */latest/meta-data/iam/security-credentials/TestRole)
        cat > "$TEST_ROOT/token-config"
        if [[ "${MALFORMED:-}" == credentials ]]; then printf '{}';
        else printf '%s' '{"Code":"Success","AccessKeyId":"EXAMPLEACCESSKEY","SecretAccessKey":"FAKESecret","Token":"FAKESession"}'; fi ;;
    https://ec2.us-east-1.amazonaws.com/)
        cat > "$TEST_ROOT/signing-config"
        [[ "${CURL_FAILURE:-}" != tags ]] || exit 22 ;;
    *) exit 99 ;;
esac
SCRIPT
    cat > "$TEST_ROOT/bin/docker" <<'SCRIPT'
#!/bin/bash
echo 'Unexpected Docker call' >> "$TEST_ROOT/calls"
exit 99
SCRIPT
    chmod +x "$TEST_ROOT/bin/curl" "$TEST_ROOT/bin/docker"
}

report() {
    run env PATH="$TEST_ROOT/bin:$PATH" WORKBENCH_CLOUD="$1" bash -x "$REPORTER" "$STATE_DIR"
}

@test "successful service termination never changes cloud status" {
    export SERVICE_RESULT=success
    report gcp
    [ "$status" -eq 0 ]
    [ ! -s "$TEST_ROOT/calls" ]
}

@test "GCE publishes a safe message before ERROR without Docker" {
    report gcp
    [ "$status" -eq 0 ]
    [ "$(wc -l < "$TEST_ROOT/calls" | tr -d ' ')" = 2 ]
    sed -n '1p' "$TEST_ROOT/calls" | grep -q 'startup_script/message'
    sed -n '2p' "$TEST_ROOT/calls" | grep -q 'startup_script/status'
    grep -q -- '--data-binary ERROR' "$TEST_ROOT/calls"
    grep -q 'release 202610080003; action repair' "$TEST_ROOT/calls"
    ! grep -q 'PRIVATE_ACTION_OUTPUT\|Docker' "$TEST_ROOT/calls"
    [[ "$output" != *PRIVATE_ACTION_OUTPUT* ]]
}

@test "GCE still attempts ERROR when the message write fails" {
    export CURL_FAILURE=message
    report gcp
    [ "$status" -ne 0 ]
    [[ "$output" == *reporting_failed* ]]
    grep -q 'startup_script/status' "$TEST_ROOT/calls"
}

@test "AWS obtains IMDSv2 credentials and signs both self-tags in one request" {
    report aws
    [ "$status" -eq 0 ]
    [ "$(wc -l < "$TEST_ROOT/calls" | tr -d ' ')" = 5 ]
    grep -q -- '--aws-sigv4 aws:amz:us-east-1:ec2' "$TEST_ROOT/calls"
    grep -q 'ResourceId.1=i-0123456789abcdef0' "$TEST_ROOT/calls"
    grep -q 'Tag.1.Key=vwbapp:startup_script/message' "$TEST_ROOT/calls"
    grep -q 'Tag.2.Key=vwbapp:startup_script/status' "$TEST_ROOT/calls"
    grep -q 'Tag.2.Value=ERROR' "$TEST_ROOT/calls"
    grep -q 'user = "EXAMPLEACCESSKEY:FAKESecret"' "$TEST_ROOT/signing-config"
    grep -q 'X-Amz-Security-Token: FAKESession' "$TEST_ROOT/signing-config"
    grep -q 'X-aws-ec2-metadata-token: FAKEMetadataToken' "$TEST_ROOT/token-config"
    ! grep -q 'FAKESecret\|FAKESession\|FAKEMetadataToken\|Docker' "$TEST_ROOT/calls"
    [[ "$output" != *FAKESecret* && "$output" != *FAKESession* && "$output" != *FAKEMetadataToken* ]]
}

@test "missing or malformed state still reports a bounded generic failure" {
    printf '%s' '{"active_version":"unsafe version"}' > "$STATE_DIR/boot.json"
    printf '%s' invalid > "$STATE_DIR/state.json"
    report gcp
    [ "$status" -eq 0 ]
    grep -q 'release unknown; action unknown' "$TEST_ROOT/calls"
    rm "$STATE_DIR/boot.json" "$STATE_DIR/state.json"
    report gcp
    [ "$status" -eq 0 ]
}

@test "malformed IMDS responses never send a signed EC2 call" {
    local malformed
    for malformed in token document role credentials; do
        : > "$TEST_ROOT/calls"
        export MALFORMED="$malformed"
        report aws
        [ "$status" -ne 0 ]
        [[ "$output" == *reporting_failed* ]]
        ! grep -q 'ec2.us-east-1' "$TEST_ROOT/calls"
    done
}

@test "reporting route timeout and authorization failures stay bounded failures" {
    export CURL_FAILURE=all
    report aws
    [ "$status" -ne 0 ]
    [ "$(wc -l < "$TEST_ROOT/calls" | tr -d ' ')" = 1 ]
    export CURL_FAILURE=tags
    report aws
    [ "$status" -ne 0 ]
    [[ "$output" == *reporting_failed* ]]
}

@test "real curl signs the complete AWS request with the temporary session token" {
    run python3 "$REPO_ROOT/scripts/test/fixtures/maintenance-signing.py" "$REPORTER" "$TEST_ROOT"
    [ "$status" -eq 0 ]
}
