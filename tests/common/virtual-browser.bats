# Smoke test for virtual-browser templates: the app runs behind a streamed Chromium locked down by a
# managed enterprise policy. Verifies the policy is actually present and enforcing in the browser
# container (application-server) and that the backend app container is up. Reads the policy on the
# host with jq via `docker exec ... cat`, so the browser image needs no jq of its own.

setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

BROWSER_CONTAINER="application-server"
# Backend container name + app origin differ per template; the per-template .sh exports them.
BACKEND_CONTAINER="${BACKEND_CONTAINER:-jupyterlab}"
POLICY_PATH="/etc/chromium/policies/managed/workbench-rbi.json"
APP_ORIGIN="${APP_ORIGIN:-http://jupyterlab:8888}"

@test "browser container is running" {
    run docker inspect -f '{{.State.Running}}' "${BROWSER_CONTAINER}"
    [ "${status}" -eq 0 ]
    [ "${output}" = "true" ]
}

@test "backend app container is running" {
    run docker inspect -f '{{.State.Running}}' "${BACKEND_CONTAINER}"
    [ "${status}" -eq 0 ]
    [ "${output}" = "true" ]
}

@test "managed policy is present and valid JSON" {
    docker exec "${BROWSER_CONTAINER}" cat "${POLICY_PATH}" | jq -e . > /dev/null
}

@test "policy allows only the app origin" {
    docker exec "${BROWSER_CONTAINER}" cat "${POLICY_PATH}" \
        | jq -e --arg o "${APP_ORIGIN}" '.URLAllowlist == [$o]' > /dev/null
}

@test "policy blocks all other navigation" {
    docker exec "${BROWSER_CONTAINER}" cat "${POLICY_PATH}" \
        | jq -e '.URLBlocklist == ["*"]' > /dev/null
}

@test "downloads are blocked" {
    docker exec "${BROWSER_CONTAINER}" cat "${POLICY_PATH}" \
        | jq -e '.DownloadRestrictions == 3' > /dev/null
}

@test "devtools and remote debugging are disabled" {
    docker exec "${BROWSER_CONTAINER}" cat "${POLICY_PATH}" \
        | jq -e '.DeveloperToolsAvailability == 2 and .RemoteDebuggingAllowed == false' > /dev/null
}

@test "clipboard-out and command are disabled AND locked in the browser env" {
    # "<value>|locked" pins the setting so a client can't re-enable it over the data websocket.
    run docker exec "${BROWSER_CONTAINER}" printenv SELKIES_CLIPBOARD_OUT_ENABLED
    [ "${status}" -eq 0 ]
    [ "${output}" = "false|locked" ]
    run docker exec "${BROWSER_CONTAINER}" printenv SELKIES_COMMAND_ENABLED
    [ "${status}" -eq 0 ]
    [ "${output}" = "false|locked" ]
}

@test "file transfers are upload-only" {
    run docker exec "${BROWSER_CONTAINER}" printenv SELKIES_FILE_TRANSFERS
    [ "${status}" -eq 0 ]
    [ "${output}" = "upload" ]
}
