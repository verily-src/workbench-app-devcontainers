# Smoke test for virtual-browser templates: the app runs behind a streamed Chromium locked down by a
# managed enterprise policy. Verifies the policy is actually present and enforcing in the browser
# container (application-server) and that the backend app container is up. Reads the policy on the
# host with jq via `docker exec ... cat`, so the browser image needs no jq of its own.

setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

BROWSER_CONTAINER="application-server"
POLICY_PATH="/etc/chromium/policies/managed/workbench-rbi.json"

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

@test "the policy file can't be modified by the user the browser actually runs as" {
    run docker exec -u abc "${BROWSER_CONTAINER}" sh -c "echo x >> ${POLICY_PATH}"
    [ "${status}" -ne 0 ]
}

@test "the app is actually serving on port 3000, not just running" {
    run docker exec "${BROWSER_CONTAINER}" curl -sf --max-time 3 -o /dev/null http://localhost:3000/
    [ "${status}" -eq 0 ]
}

@test "the backend is unreachable from a container on app-network alone" {
    run docker run --rm --network app-network curlimages/curl:latest \
        -sf --max-time 3 -o /dev/null "http://${APP_ORIGIN}"
    [ "${status}" -ne 0 ]
}

@test "the backend is reachable from a container on its own backend network" {
    local backend_network
    backend_network="$(docker inspect "${BACKEND_CONTAINER}" \
        --format '{{range $net, $_ := .NetworkSettings.Networks}}{{$net}}{{end}}')"
    run docker run --rm --network "${backend_network}" curlimages/curl:latest \
        -sf --max-time 3 -o /dev/null "http://${APP_ORIGIN}"
    [ "${status}" -eq 0 ]
}
