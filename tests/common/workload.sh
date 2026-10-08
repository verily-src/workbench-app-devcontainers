#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly SCRIPT_DIR
readonly EXECUTION_MODE="${DEPENDENCY_WORKLOAD_MODE:-cloud}"
case "${EXECUTION_MODE}" in cloud|hosted) ;; *) exit 2 ;; esac
readonly POSTGRES_IMAGE='postgres@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873'

blocked() { echo "$*" >&2; exit 3; }

python_work() {
    timeout 240 docker exec -i --user "${USER_NAME}" application-server python3 - "$1" < "${SCRIPT_DIR}/workloads/python.py"
}

http_work() {
    for _ in {1..10}; do curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:${PORT}/" >/dev/null; done
}

docker_work() {
    local image
    image=$(docker inspect --format '{{.Image}}' application-server)
    timeout 120 docker exec application-server docker run -d --name dependency-child --entrypoint python3 "${image}" \
        -c 'import pathlib,time; p=pathlib.Path("/tmp/fixture"); p.write_bytes(b"x"*1048576); assert p.stat().st_size==1048576; time.sleep(1800)' > /dev/null
    for _ in {1..30}; do
        if docker exec dependency-child test -s /tmp/fixture; then return; fi
        sleep 1
    done
    return 1
}

postgres_work() {
    local network password='dependency-fixture-only' database session
    network=$(docker inspect application-server --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' | head -1)
    timeout 180 docker pull "${POSTGRES_IMAGE}"
    docker run -d --name dependency-postgres --network "${network}" -e "POSTGRES_PASSWORD=${password}" "${POSTGRES_IMAGE}" >/dev/null
    for _ in {1..60}; do
        if docker exec dependency-postgres pg_isready -U postgres; then break; fi
        sleep 1
    done
    docker exec -i dependency-postgres psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE fixture AS SELECT i AS id, i % 100 AS group_id FROM generate_series(1, 100000) i;
SELECT COUNT(*) FROM fixture HAVING COUNT(*) = 100000;
SQL
    database="postgres://postgres:${password}@dependency-postgres:5432/postgres?sslmode=disable"
    session=$(cat /proc/sys/kernel/random/uuid)
    curl --fail --silent --show-error --max-time 20 -X POST "http://127.0.0.1:${PORT}/api/connect" \
        -H "x-session-id: ${session}" --data-urlencode "url=${database}" > "${OUTPUT_DIR}/postgres-session.json"
    for _ in {1..5}; do
        curl --fail --silent --show-error --max-time 20 -H "x-session-id: ${session}" \
            --data-urlencode 'query=SELECT group_id, COUNT(*) FROM fixture GROUP BY group_id' \
            "http://127.0.0.1:${PORT}/api/query" | jq -e '.rows | length == 100' >/dev/null
    done
}

playground_work() {
    local image request id state caddy_config
    image=$(docker inspect --format '{{.Config.Image}}' application-server)
    caddy_config='@{{.AppName}} path /{{.AppName}} /{{.AppName}}/*
route @{{.AppName}} {
    uri strip_prefix /{{.AppName}}
    reverse_proxy {{.ContainerName}}:{{.Port}}
}'
    request=$(jq -nc --arg image "${image}" --arg caddy "${caddy_config}" '{app_name:"dependency-fixture",username:"root",user_home_directory:"/root",port:8080,
      optional_features:[],dockerfile:("FROM "+$image+"\nRUN mkdir -p /srv && echo dependency-workload-ok > /srv/index.html\nENTRYPOINT [\"caddy\"]\nCMD [\"file-server\",\"--listen\",\":8080\",\"--root\",\"/srv\"]"),caddy_config:$caddy}')
    id=$(curl --fail --silent --show-error --max-time 15 -H 'Content-Type: application/json' \
        -d "${request}" "http://127.0.0.1:${PORT}/_app" | jq -er '.id')
    printf '%s\n' "${id}" > "${OUTPUT_DIR}/playground-child-id"
    for _ in {1..180}; do
        state=$(curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:${PORT}/_app/${id}" | jq -r '.status')
        if [[ "${state}" == failed ]]; then
            echo 'Playground fixture build failed' >&2
            curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:${PORT}/_app/logs?tail=100" >&2 || true
            return 1
        fi
        if [[ "${state}" == active ]]; then break; fi
        sleep 2
    done
    [[ "${state}" == active ]]
    curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:${PORT}/dependency-fixture/" | grep -q dependency-workload-ok
    jq --arg child "app-${id}" '. + [$child]' "${OUTPUT_DIR}/expected-containers.json" > "${OUTPUT_DIR}/expected-containers.tmp"
    mv "${OUTPUT_DIR}/expected-containers.tmp" "${OUTPUT_DIR}/expected-containers.json"
}

expected_services() {
    local project service ids name
    project=$(docker inspect application-server --format '{{index .Config.Labels "com.docker.compose.project"}}')
    [[ -n "${project}" ]]
    printf '[]\n' > "${OUTPUT_DIR}/expected-containers.json"
    while read -r service; do
        ids=$(docker ps -q --filter "label=com.docker.compose.project=${project}" --filter "label=com.docker.compose.service=${service}")
        [[ -n "${ids}" && "${ids}" != *$'\n'* ]]
        name=$(docker inspect --format '{{.Name}}' "${ids}")
        jq --arg name "${name#/}" '. + [$name]' "${OUTPUT_DIR}/expected-containers.json" > "${OUTPUT_DIR}/expected-containers.tmp"
        mv "${OUTPUT_DIR}/expected-containers.tmp" "${OUTPUT_DIR}/expected-containers.json"
    done < <(jq -r --arg app "${APP}" '.apps[$app].services[]' "${SCRIPT_DIR}/profiles.json")
}

llm_work() {
    local user_home
    user_home=$(jq -r --arg app "${APP}" '.apps[$app].home' "${SCRIPT_DIR}/profiles.json")
    timeout 30 docker exec --user "${USER_NAME}" application-server claude --version
    timeout 30 docker exec --user "${USER_NAME}" application-server gemini --version
    if [[ "${EXECUTION_MODE}" == hosted ]]; then
        docker exec application-server mkdir -p /tmp/dependency-workload-bin
        docker cp "${SCRIPT_DIR}/workloads/wb" application-server:/tmp/dependency-workload-bin/wb
        docker exec application-server chmod 755 /tmp/dependency-workload-bin /tmp/dependency-workload-bin/wb
        # shellcheck disable=SC2016
        timeout 180 docker exec --user "${USER_NAME}" application-server bash -c \
            'export PATH="/tmp/dependency-workload-bin:$PATH"; exec /opt/llm-context/generate-context.sh "$1"' bash "${user_home}"
    else
        timeout 180 docker exec --user "${USER_NAME}" application-server /opt/llm-context/generate-context.sh "${user_home}"
    fi
    docker exec --user "${USER_NAME}" application-server test -s "${user_home}/.claude/CLAUDE.md"
    docker cp application-server:/opt/llm-context/templates "${OUTPUT_DIR}/generated-templates"
    printf '[]\n' > "${OUTPUT_DIR}/generated-template-results.json"
    for template in file-processor flask-api rshiny-dashboard streamlit-dashboard; do
        docker exec application-server test -s "/opt/llm-context/templates/${template}/Dockerfile"
        docker exec application-server test -s "/opt/llm-context/templates/${template}/devcontainer-template.json"
        docker compose -f "${OUTPUT_DIR}/generated-templates/${template}/docker-compose.yaml" config --quiet
        jq --arg template "${template}" '. + [{template:$template,mode:"render",status:"pass",independent_memory:false}]' \
            "${OUTPUT_DIR}/generated-template-results.json" > "${OUTPUT_DIR}/generated-template-results.tmp"
        mv "${OUTPUT_DIR}/generated-template-results.tmp" "${OUTPUT_DIR}/generated-template-results.json"
    done
}

run_workload() {
    local config kind gpu
    config=$(jq -ec --arg app "${APP}" '.apps[$app]' "${SCRIPT_DIR}/profiles.json")
    USER_NAME=$(jq -r '.user' <<< "${config}")
    PORT=$(jq -r '.port' <<< "${config}")
    kind=$(jq -r '.kind' <<< "${config}")
    timeout 10 docker inspect application-server --format '{{.State.Running}}' | grep -qx true
    if [[ "${PROFILE}" != cpu ]]; then
        gpu=$(timeout 10 nvidia-smi --query-gpu=name --format=csv,noheader)
        [[ $(wc -l <<< "${gpu}" | tr -d ' ') == 1 ]] || blocked 'exactly one GPU is required by this workload'
        case "${PROFILE}:${kind}:${APP}" in
            a100-80gb:nemo:*) [[ "${gpu}" == *A100*80GB* ]] || blocked 'NeMo requires A100-80GB' ;;
            t4:parabricks:*|t4:notebook:custom-workbench-jupyter-template) [[ "${gpu}" == *T4* ]] || blocked 'T4 is required' ;;
            *) blocked 'GPU profile is not allowed for this app' ;;
        esac
    fi
    expected_services
    sleep 60
    case "${kind}" in
        notebook) python_work notebook ;;
        nemo) python_work notebook; [[ "${PROFILE}" == cpu ]] || python_work nemo ;;
        parabricks)
            python_work notebook
            if [[ "${PROFILE}" != cpu ]]; then
                timeout 900 docker exec -i --user "${USER_NAME}" application-server bash < "${SCRIPT_DIR}/workloads/parabricks.sh"
            fi ;;
        r) timeout 180 docker exec -i --user "${USER_NAME}" application-server Rscript - < "${SCRIPT_DIR}/workloads/r.R" ;;
        editor|terminal) python_work files ;;
        http)
            if [[ "${APP}" == test-app-secrets ]]; then
                timeout 10 docker exec application-server test ! -p /tmp/secrets || blocked 'synthetic secrets have not been delivered'
            fi ;;
        postgres) postgres_work ;;
        playground) playground_work ;;
        sas)
            timeout 10 docker exec application-server sh -c 'test -r /sasinside/SASLicense.jwt && command -v sas' >/dev/null || blocked 'existing SAS license or executable unavailable'
            timeout 180 docker exec -i --user sas application-server sas -stdio <<'SAS'
data fixture; do id=1 to 100000; group=mod(id,100); value=id/100; output; end; run;
proc means data=fixture n mean; class group; var value; run;
SAS
            ;;
        access-logging)
            [[ $(docker inspect application-server --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^DC_ACCESS_ENV=//p') == test ]] || blocked 'DC_ACCESS_ENV must be test before startup'
            timeout 120 docker exec -i -e DC_ACCESS_ENV=test application-server python3 - < "${SCRIPT_DIR}/workloads/access-logging.py" ;;
        *) blocked 'no workload for app' ;;
    esac
    if [[ $(jq -r '.browser // false' <<< "${config}") == true ]]; then
        docker exec browser curl --fail --silent --max-time 10 http://localhost:3000/ >/dev/null
        docker exec browser curl --fail --silent --max-time 10 "http://application-server:${PORT}/" >/dev/null
    else
        http_work
    fi
    case "${APP}" in vscode-docker|workbench-jupyter-docker) docker_work ;; esac
    case "${APP}" in vscode-with-llm|workbench-jupyter-with-llm) llm_work ;; esac
    if [[ "${PROFILE}" == t4 && "${kind}" == notebook ]]; then python_work gpu; fi
    sleep 60
}

if [[ "${1:-}" == _run ]]; then
    readonly APP="$2" PROFILE="$3" OUTPUT_DIR="$4"
    run_workload
    exit
fi
[[ $# == 3 ]] || { echo "Usage: $0 APP {cpu|t4|a100-80gb} OUTPUT_DIR" >&2; exit 2; }
readonly APP="$1" PROFILE="$2" OUTPUT_DIR="$3"
jq -e --arg app "${APP}" '.apps | has($app)' "${SCRIPT_DIR}/profiles.json" >/dev/null
case "${PROFILE}" in cpu|t4|a100-80gb) ;; *) exit 2 ;; esac
mkdir -p "${OUTPUT_DIR}"
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
status=0
timeout 1200 bash "$0" _run "${APP}" "${PROFILE}" "${OUTPUT_DIR}" > "${OUTPUT_DIR}/workload.log" 2>&1 || status=$?
result=fail
[[ "${status}" != 0 ]] || result=pass
[[ "${status}" != 3 ]] || result=blocked
expected='["application-server"]'
[[ ! -f "${OUTPUT_DIR}/expected-containers.json" ]] || expected=$(cat "${OUTPUT_DIR}/expected-containers.json")
case "${APP}" in
    pgweb) expected='["application-server","dependency-postgres"]' ;;
    vscode-docker|workbench-jupyter-docker) expected='["application-server","dependency-child"]' ;;
esac
hash=$(cat "${SCRIPT_DIR}/workload.sh" "${SCRIPT_DIR}/profiles.json" "${SCRIPT_DIR}"/workloads/* | sha256sum | cut -d ' ' -f 1)
jq -n --arg app "${APP}" --arg profile "${PROFILE}" --arg started "${started}" --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg status "${result}" --arg mode "${EXECUTION_MODE}" --arg hash "${hash}" --argjson code "${status}" --argjson expected "${expected}" \
    '{schema_version:1,app:$app,profile:$profile,status:$status,execution_mode:$mode,reason:(if $status=="pass" then "" else "See workload.log" end),
      started_at:$started,finished_at:$finished,exit_code:$code,workload_sha256:$hash,fixture_version:1,seed:189771,
      expected_containers:$expected,gpu_workload:($profile!="cpu"),external_llm_inference:"not tested"}' > "${OUTPUT_DIR}/workload.json"
exit "${status}"
