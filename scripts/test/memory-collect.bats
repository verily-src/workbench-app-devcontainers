#!/usr/bin/env bats

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    export CGROUP_ROOT="${BATS_TEST_TMPDIR}/cgroup"
    export REPORT="${BATS_TEST_TMPDIR}/report"
    mkdir -p "${CGROUP_ROOT}/app" "${REPORT}/cgroups"
    printf '104857600\n' > "${CGROUP_ROOT}/app/memory.peak"
    printf '1048576\n' > "${CGROUP_ROOT}/app/memory.current"
    printf '536870912\n' > "${CGROUP_ROOT}/app/memory.max"
    printf '0\n' > "${CGROUP_ROOT}/app/memory.swap.peak"
    printf 'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n' > "${CGROUP_ROOT}/app/memory.events"
    sed -n '/^capture_group() {/,/^}/p; /^missing() /p' "${REPO_ROOT}/tests/common/memory-collect.sh" > "${BATS_TEST_TMPDIR}/functions.sh"
    source "${BATS_TEST_TMPDIR}/functions.sh"
}

@test "kernel peak retains a short allocation after current use falls" {
    capture_group "${REPORT}" /app app app start '' false
    jq -e '.peak_bytes==104857600 and .current_bytes==1048576 and .final_capture' "${REPORT}"/cgroups/*.json
    printf '1024\n' > "${CGROUP_ROOT}/app/memory.peak"
    capture_group "${REPORT}" /app app app start '' false
    jq -e '.peak_bytes==104857600' "${REPORT}"/cgroups/*.json
}

@test "child OOM is captured when Docker says the parent survived" {
    printf 'low 0\nhigh 0\nmax 10\noom 2\noom_kill 1\n' > "${CGROUP_ROOT}/app/memory.events"
    capture_group "${REPORT}" /app app app start '' false
    jq -e '.oom_delta==2 and .oom_kill_delta==1' "${REPORT}"/cgroups/*.json
}

@test "missing and corrupt counters cannot become passing zero measurements" {
    rm "${CGROUP_ROOT}/app/memory.peak"
    capture_group "${REPORT}" /app app app start '' false
    grep -q 'missing cgroup peak' "${REPORT}/missing.txt"
    printf 'invalid\n' > "${CGROUP_ROOT}/app/memory.peak"
    capture_group "${REPORT}" /app app app start '' false
    grep -q 'invalid cgroup counters' "${REPORT}/missing.txt"
}

@test "lost cgroup clears final capture instead of reusing an old peak" {
    capture_group "${REPORT}" /app app app start '' false
    rm "${CGROUP_ROOT}/app/memory.peak"
    capture_group "${REPORT}" /app app app start '' false
    jq -e '.final_capture==false' "${REPORT}"/cgroups/*.json
}

@test "container restart keeps distinct lifecycle records" {
    capture_group "${REPORT}" /app app app first '' false
    capture_group "${REPORT}" /app app app second '' false
    [ "$(find "${REPORT}/cgroups" -name '*.json' | wc -l | tr -d ' ')" = 2 ]
}

@test "observed unlimited and missing limits are distinct" {
    printf 'max\n' > "${CGROUP_ROOT}/app/memory.max"
    capture_group "${REPORT}" /app app app start '' false
    jq -e '.limit_bytes==null and .limit_unlimited' "${REPORT}"/cgroups/*.json
    printf 'bad\n' > "${CGROUP_ROOT}/app/memory.max"
    capture_group "${REPORT}" /app app app start '' false
    grep -q 'invalid cgroup limit' "${REPORT}/missing.txt"
}
