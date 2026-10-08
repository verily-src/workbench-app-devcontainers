#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../../.." && pwd)"
    COLLECTOR="${REPO_ROOT}/tests/common/memory-collect.sh"
    REPORT="${BATS_TEST_TMPDIR}/report"
    jq -n '{schema_version:1,run_id:"memory-integration",app:"example",cloud:"gcp",profile:"cpu",sample:1,
      inputs_hash:"fixture",source_sha:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",machine:{type:"ci",ram_bytes:0,gpu_type:"",gpu_count:0}}' > "${BATS_TEST_TMPDIR}/context.json"
    jq -n '{status:"pass",execution_mode:"cloud",workload_sha256:"fixture",expected_containers:["application-server"]}' > "${BATS_TEST_TMPDIR}/workload.json"
}

teardown() {
    if [[ -f "${REPORT}/collector.pid" && ! -f "${REPORT}/collector.exit" ]]; then
        touch "${REPORT}/stop"
        "${COLLECTOR}" finish "${REPORT}" "${BATS_TEST_TMPDIR}/workload.json" || true
    fi
    docker ps -aq --filter label=dependency-memory-integration=true | xargs -r docker rm -f >/dev/null
}

@test "real cgroup peak captures a child spike shorter than the polling interval" {
    "${COLLECTOR}" start "${BATS_TEST_TMPDIR}/context.json" "${REPORT}"
    docker run -d --name application-server --label dependency-memory-integration=true --memory 512m \
        python:3.12-alpine python -c 'import time; time.sleep(300)' >/dev/null
    sleep 2
    docker exec application-server python -c 'import time; data=bytearray(128*1024*1024); time.sleep(0.03)'
    "${COLLECTOR}" finish "${REPORT}" "${BATS_TEST_TMPDIR}/workload.json"
    jq -e 'any(.cgroups[]; .role=="app" and .peak_bytes>=134217728)' "${REPORT}/memory.json"
}

@test "real child OOM fails collection while its parent container stays running" {
    "${COLLECTOR}" start "${BATS_TEST_TMPDIR}/context.json" "${REPORT}"
    docker run -d --name application-server --label dependency-memory-integration=true --memory 96m --memory-swap 96m \
        python:3.12-alpine python -c 'import time; time.sleep(300)' >/dev/null
    sleep 2
    run docker exec application-server python -c 'data=bytearray(256*1024*1024)'
    [ "${status}" -ne 0 ]
    [ "$(docker inspect application-server --format '{{.State.Running}}')" = true ]
    run "${COLLECTOR}" finish "${REPORT}" "${BATS_TEST_TMPDIR}/workload.json"
    [ "${status}" -ne 0 ]
    jq -e 'any(.cgroups[]; .oom_kill_delta>0)' "${REPORT}/memory.json"
}

@test "sidecar cgroups are measured separately from the application" {
    "${COLLECTOR}" start "${BATS_TEST_TMPDIR}/context.json" "${REPORT}"
    docker run -d --name application-server --label dependency-memory-integration=true --memory 512m \
        python:3.12-alpine python -c 'import time; time.sleep(300)' >/dev/null
    docker run -d --name browser --label dependency-memory-integration=true --memory 512m \
        python:3.12-alpine python -c 'import time; data=bytearray(64*1024*1024); time.sleep(300)' >/dev/null
    sleep 2
    jq '.expected_containers += ["browser"]' "${BATS_TEST_TMPDIR}/workload.json" > "${BATS_TEST_TMPDIR}/both.json"
    "${COLLECTOR}" finish "${REPORT}" "${BATS_TEST_TMPDIR}/both.json"
    jq -e '[.cgroups[]|select(.role=="app")]|length==2' "${REPORT}/memory.json"
}

@test "an observed child removed before finish cannot leave a passing sample" {
    "${COLLECTOR}" start "${BATS_TEST_TMPDIR}/context.json" "${REPORT}"
    docker run -d --name application-server --label dependency-memory-integration=true --memory 512m \
        python:3.12-alpine python -c 'import time; time.sleep(300)' >/dev/null
    child=$(docker run -d --name dependency-removed-child --label dependency-memory-integration=true --memory 512m \
        python:3.12-alpine python -c 'import time; data=bytearray(64*1024*1024); time.sleep(300)')
    for _ in {1..150}; do
        if jq -es --arg id "${child}" 'any(.[]; .container_id==$id and .final_capture)' "${REPORT}"/cgroups/*.json >/dev/null 2>&1; then break; fi
        sleep 0.1
    done
    jq -es --arg id "${child}" 'any(.[]; .container_id==$id and .final_capture)' "${REPORT}"/cgroups/*.json >/dev/null
    docker rm -f "${child}" >/dev/null
    run "${COLLECTOR}" finish "${REPORT}" "${BATS_TEST_TMPDIR}/workload.json"
    [ "${status}" -ne 0 ]
    jq -e --arg id "${child}" 'any(.cgroups[]; .container_id==$id and .final_capture==false)' "${REPORT}/memory.json"
}
