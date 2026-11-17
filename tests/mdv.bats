# Smoke tests for the MDV template: MDV behind nginx with cross-origin isolation, so it gets
# SharedArrayBuffer inside Workbench's (non-isolated) iframe; the sample project shown when no
# bucket has MDV data; and workspace data. CI has no Workbench buckets, so setup_file stages a
# read-only "bucket" the way start-workspace-sync.sh exposes real ones (a read-only bind mount
# listed in resources.txt). Tests run in file order: sample tests come before the bucket gets
# MDV data, which retires the samples.

CONTAINER_NAME="${CONTAINER_NAME:-application-server}"
PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright:v1.56.1-noble"
STATE_DIR="/var/lib/mdv-workspace-sync"
RO_ROOT="/mnt/mdv-workspace-ro"
# A Workbench folder containing a bucket, as `wb resource mount` lays them out.
BUCKET="bats-folder/bats-bucket"
BUCKET_SRC="/tmp/bats-bucket"

in_app() {
    docker exec --user root "${CONTAINER_NAME}" bash -c "set -o errexit -o pipefail; $1"
}

as_app_user() {
    docker exec --user pn "${CONTAINER_NAME}" bash -c "set -o errexit -o pipefail; $1"
}

mdv_get() {
    in_app "curl -fsS 'http://localhost:5055$1'"
}

project_names() {
    mdv_get /projects | jq -r '.[].name'
}

wait_for_project() {
    local name="$1" timeout="${2:-300}" waited=0
    until project_names | grep -qx "${name}"; do
        if (( waited >= timeout )); then
            in_app "tail -40 ${STATE_DIR}/sync.log" >&3
            return 1
        fi
        sleep 5
        waited=$(( waited + 5 ))
    done
}

# Full sync pass; retries while the background loop holds the sync lock.
run_sync() {
    local output
    for _ in $(seq 1 60); do
        output="$(as_app_user "python3 /opt/mdv-workbench/mdv_workspace_sync.py" 2>&1)" || return 1
        if ! grep -q "another sync is running" <<< "${output}"; then
            echo "${output}"
            return 0
        fi
        sleep 5
    done
    echo "sync lock still held: ${output}"
    return 1
}

setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
    # MDV, then the startup sync, come up after the container starts.
    local waited=0
    until in_app "curl -fsS -o /dev/null http://localhost:5055/projects" 2> /dev/null; do
        (( waited >= 300 )) && { echo "MDV did not respond on port 5055" >&3; return 1; }
        sleep 5
        waited=$(( waited + 5 ))
    done
}

teardown_file() {
    in_app "umount -l '${RO_ROOT}/${BUCKET}' 2> /dev/null || true
            sed -i '\|^${BUCKET}\$|d' '${STATE_DIR}/resources.txt' 2> /dev/null || true
            rm -rf '${BUCKET_SRC}'" || true
}

@test "MDV is served through nginx on port 5055" {
    mdv_get / | grep -qi "<html"
}

@test "the MDV document has Document-Isolation-Policy and one matching COEP header" {
    local headers
    headers="$(in_app "curl -fsS -D - -o /dev/null http://localhost:5055/" | tr -d '\r')"
    grep -qix "Document-Isolation-Policy: isolate-and-credentialless" <<< "${headers}"
    grep -qix "Cross-Origin-Embedder-Policy: credentialless" <<< "${headers}"
    # MDV's own `require-corp` must be replaced, not duplicated, or no-CORS images break.
    [ "$(grep -ci "^Cross-Origin-Embedder-Policy:" <<< "${headers}")" -eq 1 ]
}

@test "MDV gets SharedArrayBuffer inside a cross-origin iframe, without isolating the parent" {
    # Chromium full build (not the headless shell, which lacks Document-Isolation-Policy). The
    # parent page is a non-isolated about:blank document, like Workbench's UI. Plain-http CI
    # origins aren't secure contexts, so the app's origin is marked secure for the test.
    local script
    script="$(cat <<'EOF'
const { chromium } = require('playwright');
(async () => {
  const url = process.env.MDV_URL;
  const browser = await chromium.launch({
    channel: 'chromium',
    args: [`--unsafely-treat-insecure-origin-as-secure=${new URL(url).origin}`],
  });
  const page = await browser.newPage();
  await page.setContent(`<iframe src="${url}" width="1200" height="800"></iframe>`);
  const frame = await (await page.waitForSelector('iframe')).contentFrame();
  await frame.waitForLoadState('load');
  const result = {
    parentIsolated: await page.evaluate(() => self.crossOriginIsolated),
    ...(await frame.evaluate(() => ({
      frameIsolated: self.crossOriginIsolated,
      sharedMemory: typeof SharedArrayBuffer === 'function'
        && new WebAssembly.Memory({ initial: 1, maximum: 1, shared: true }).buffer
          instanceof SharedArrayBuffer,
    }))),
  };
  // The Workspace data entry point is injected into MDV's own pages.
  await frame.getByText('Open from workspace').first().waitFor({ timeout: 60000 });
  console.log(JSON.stringify(result));
  await browser.close();
  process.exit(result.frameIsolated && result.sharedMemory && !result.parentIsolated ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(1); });
EOF
)"
    run docker run --rm --network app-network --ipc=host -e MDV_URL="http://${CONTAINER_NAME}:5055/" \
        -e SCRIPT="${script}" "${PLAYWRIGHT_IMAGE}" bash -c \
        'cd /tmp && npm install --silent --no-audit --no-fund playwright@1.56.1 > /dev/null && node -e "${SCRIPT}"'
    echo "${output}"
    [ "${status}" -eq 0 ]
}

@test "the Workspace data browser script is injected into MDV's pages" {
    mdv_get / | grep -qF '<script src="/_workspace/ui.js" defer></script>'
    mdv_get /_workspace/ui.js > /dev/null
}

@test "MDV's database is reachable from the app but not on app-network or the host" {
    in_app "getent hosts mdv_db > /dev/null"
    local project db
    project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "${CONTAINER_NAME}")"
    db="$(docker ps -q --filter "label=com.docker.compose.project=${project}" \
        --filter "label=com.docker.compose.service=mdv_db")"
    [ -n "${db}" ]
    [ -z "$(docker inspect -f '{{range $net, $_ := .NetworkSettings.Networks}}{{if eq $net "app-network"}}x{{end}}{{end}}' "${db}")" ]
    [ -z "$(docker port "${db}")" ]
}

@test "the sample project is shown when no workspace bucket has MDV data" {
    wait_for_project sample--pbmc3k-processed
}

@test "stage a read-only workspace bucket" {
    in_app "
        mkdir -p '${BUCKET_SRC}/experiments' '${BUCKET_SRC}/mdv/data' '${BUCKET_SRC}/mdv/projects'
        python3 - <<'EOF'
import csv, random
random.seed(1)
for path in ('${BUCKET_SRC}/experiments/cells.csv', '${BUCKET_SRC}/mdv/data/auto-cells.csv'):
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['x', 'y', 'cluster'])
        for _ in range(500):
            w.writerow([random.gauss(0, 1), random.gauss(0, 1), random.choice('ABC')])
EOF
        cp -r /opt/mdv-samples/pbmc3k-processed '${BUCKET_SRC}/mdv/projects/linked-pbmc'
        rm -f '${BUCKET_SRC}/mdv/projects/linked-pbmc/.mdv-sample-complete'
        mkdir -p '${RO_ROOT}/${BUCKET}'
        mount --bind '${BUCKET_SRC}' '${RO_ROOT}/${BUCKET}'
        mount -o remount,bind,ro '${RO_ROOT}/${BUCKET}'
        echo '${BUCKET}' >> '${STATE_DIR}/resources.txt'"
}

@test "the browser lists Workbench folders, buckets and importable files" {
    mdv_get "/_workspace/api/list?path=" \
        | jq -e '.entries | any(.name == "bats-folder" and .type == "wbfolder")'
    mdv_get "/_workspace/api/list?path=bats-folder" \
        | jq -e '.entries | any(.path == "bats-folder/bats-bucket" and .type == "bucket")'
    mdv_get "/_workspace/api/list?path=${BUCKET}/experiments" \
        | jq -e '.entries | any(.name == "cells.csv" and .importable and .kind == "table")'
    mdv_get "/_workspace/api/list?path=${BUCKET}/mdv/projects" \
        | jq -e '.entries | any(.name == "linked-pbmc" and .type == "project")'
}

@test "the browser rejects paths outside workspace buckets" {
    local code
    for path in "../../etc" "${BUCKET}/../../../etc" "not-mounted"; do
        code="$(in_app "curl -s -o /dev/null -w '%{http_code}' \
            'http://localhost:5055/_workspace/api/list?path=${path}'")"
        [ "${code}" -eq 400 ]
    done
}

@test "workspace data is read-only to MDV" {
    run as_app_user "touch '${RO_ROOT}/${BUCKET}/experiments/new-file'"
    [ "${status}" -ne 0 ]
}

@test "Open from workspace converts a file into an MDV project" {
    local job state waited=0
    job="$(in_app "curl -fsS -X POST -H 'Content-Type: application/json' \
        -d '{\"path\": \"${BUCKET}/experiments/cells.csv\"}' \
        http://localhost:5055/_workspace/api/import" | jq -r .id)"
    until state="$(mdv_get "/_workspace/api/jobs/${job}" | jq -r .state)" && [ "${state}" != running ]; do
        (( waited >= 300 )) && break
        sleep 5
        waited=$(( waited + 5 ))
    done
    mdv_get "/_workspace/api/jobs/${job}" | jq -e '.state == "done" and .project_name == "cells"'
    project_names | grep -qx cells
    # The project's README records where the data came from.
    in_app "grep -q 'experiments/cells.csv' /app/mdv/cells/README.md"
}

@test "opening the same file again reuses its project" {
    in_app "curl -fsS -X POST -H 'Content-Type: application/json' \
        -d '{\"path\": \"${BUCKET}/experiments/cells.csv\"}' \
        http://localhost:5055/_workspace/api/import" \
        | jq -e '.state == "done" and .project_name == "cells"'
}

@test "the sync picks up the bucket's mdv/ folder and retires the samples" {
    run_sync
    project_names | grep -qx auto-cells
    project_names | grep -qx linked-pbmc
    [ -z "$(project_names | grep "^sample--" || true)" ]
}

@test "linked projects read data from the bucket and keep view state local" {
    in_app "
        data=\$(find /app/mdv/linked-pbmc -type l | head -1)
        [[ -n \"\${data}\" && \"\$(readlink -f \"\${data}\")\" == '${RO_ROOT}/${BUCKET}/'* ]]
        for f in views.json state.json datasources.json; do
            [[ -f /app/mdv/linked-pbmc/\${f} && ! -L /app/mdv/linked-pbmc/\${f} ]]
        done"
}

@test "removing data from the bucket removes its project" {
    in_app "rm '${BUCKET_SRC}/mdv/data/auto-cells.csv'"
    run_sync
    [ -z "$(project_names | grep -x auto-cells || true)" ]
    in_app "[[ ! -e /app/mdv/auto-cells ]]"
    project_names | grep -qx linked-pbmc
}
